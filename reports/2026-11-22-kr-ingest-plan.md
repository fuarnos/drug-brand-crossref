# 韩国 KR（HIRA 약가마스터）入库准备报告 —— v1.2.0 干跑与计划

- 日期：2026-11-22（北京时间）｜工位：backend｜任务：`task-8`（T8，P1）
- 状态：**准备完成，未写 `data/drugs.db`**（等 Lead 开放写库窗口）；干跑只在 `.tmp/kr_dryrun.db` 副本上做，副本已演练「写库 → check_data → 回滚」并回到基线。
- 依据：`reports/2026-11-22-kr-license-assessment.md`（data-scout，2026-11-22）候选 B = data.go.kr **15067462**（표준코드）+ **15067461**（주성분）。
- 口径（页面文案由 frontend 负责，本报告只给数据与缺口）：**HIRA 약가마스터 是医保药价清单（급여 목록），不是韩国注册库全量**；`취소일자` 只表示「不在药价表内」，**不等于批文撤销**；HIRA **没有 허가번호**。

## 0 结论先行

| 项 | 结果 |
|---|---|
| 快照 | 两份官方 CSV 已在 `data/raw/kr/20261122/`（data-scout 2026-11-22 落盘），本轮**校验复用、未重复下载**；`data/raw/kr/fetch_meta.json` 已写 URL / 时间 / 大小 / sha256 / 行数 |
| 条数 | 표준코드 **309,889 行 / 97,356 品目 / 109,231 唯一商品名**；주성분 **60,750 行 / 20,465 配方码** |
| 计划 | **97,356 个 product**（一行 = 一个品目）；**117,500 个成分行**（含含量）；**110,178 条商品名**（品目内多写法） |
| 成分映射 | **94,915 / 117,500 = 80.8%** 落到既有 substance 主档；新建 **2,547** 个 substance（英文 22,268 成分行 / 韩文 317 成分行） |
| 覆盖率 | 包装 **93,779 / 97,356 = 96.3%**；剂型结构化 **50,527 = 51.9%**（无成分码的品目不臆造剂型）；MAH **100%**；ATC **68,939 = 70.8%** |
| 状态 | `active`（在药价表内）**65,086**；`unknown`（有真实취소일자，**不判撤销**）**32,270** |
| 干跑库 | `product` 633,722 → **731,078**（+97,356）；`check_data` **exit 0**、FK **0**；副本回滚**逐表差异 0** |
| schema | `country` 枚举**已含 KR**（v0.11.3 枚举先行）；`init_db` 对现库 **no-op**，**不需要重建 product 表** |
| 卡点 | **只有写库窗口**（v1.1.1 发布期间不写主库）；无许可/字段/账号卡点 |

## 1 数据源、许可与署名

| 项 | 值 |
|---|---|
| 数据集页 | <https://www.data.go.kr/data/15067462/fileData.do> · <https://www.data.go.kr/data/15067461/fileData.do> |
| 文件直链（匿名） | `…/fileDownload.do?atchFileId=FILE_000000007666876&fileDetailSn=1`（표준코드） · `atchFileId=FILE_000000007759104`（주성분） |
| 许可 | **공공저작물 : 출처표시 (제1유형 / KOGL Type 1)** — 可商用、可演绎、须标明出处；<https://www.kogl.or.kr/info/licenseType1.do> |
| 免账号 | 页面原文「파일데이터는 로그인 없이 다운로드를 통해 이용하실 수 있습니다」；本轮匿名复用快照 |
| 数据截止 | 표준코드 **2026-08-31**（분기，파일명 `…20260831`）/ 주성분 **2026-11-05**（연간） |
| 抓取日 | 2026-11-22（北京时间；scout 落盘 2026-11-21 本地） |
| UA | `drug-brand-crossref/0.2 (public-data research; +https://drugcrossref.com/; HIRA medprice ingest, one download per DB window)` |
| 边界 | 不转载说明书正文、不存价格、不做剂量换算；不做「韩国全部药品」表述 |

**建议署名句式**（页面 / 覆盖页 / datapackage）：
- 韩：`출처: 건강보험심사평가원, 「약가마스터_의약품표준코드/의약품주성분」(공공데이터포털, 공공누리 제1유형), 기준일 2026-08-31. DrugCrossRef에서 정규화함.`
- 英：`Source: Health Insurance Review & Assessment Service (HIRA), "약가마스터 (drug price master)" via data.go.kr, Korea Open Government Licence Type 1 (KOGL Type 1), data as of 2026-08-31. Normalised by DrugCrossRef.`
- 中：`来源：韩国健康保险审查评价院（HIRA）「약가마스터（医保药价清单）」，经 data.go.kr 发布，공공누리 第1유형（KOGL Type 1，须标明出处）；数据基准日 2026-08-31；本站已做归一化。`

## 2 抓取结果（`data/raw/kr/fetch_meta.json`）

| 文件 | 数据集 | 大小 | 行数 | sha256（前 16） | 编码/列 |
|---|---|---|---:|---|---|
| `hira_yakga_stdcode_20260831.csv` | 15067462 | 55,741,167 B | **309,889** | `2d00689474851d81…` | CP949 / 22 列 |
| `hira_yakga_ingredient_20261105.csv` | 15067461 | 3,836,693 B | **60,750** | `0df509cfc612dfd4…` | CP949 / 8 列 |

- 与 data-scout README 记录的大小/哈希一致；**本轮未再下载**（`--fetch` 幂等：已存在非空即跳过，`--force` 才重下）。
- 两份文件均匿名取得（官方明示免登录）；`data/raw/` gitignored，**原始 CSV 不入库**。

## 3 口径与字段映射（`etl/ingest_kr.py`）

**一行 product = 一个品目（`품목기준코드`，97,356）**：品目内多个 `표준코드` 是不同包装条码；名字/包装/状态按品目聚合（与 `coverage` 的「品目」口径一致）。

| 来源字段 | DB | 说明 |
|---|---|---|
| `한글상품명` | `product_name`（trade，品目内**所有写法**） | 110,178 条名行（109,231 唯一名）；主名取品目内出现最多的一种 |
| `품목기준코드` | `product_id = KR-<품목기준코드>` + `approval_id` | **MFDS 品目码，不是 허가번호**；HIRA 无 허가번호（缺口见 §6） |
| `약품규격` + `제품총수량` + `제형구분` + `포장형태` | `pack` | 如 `250밀리그램 16정 PTP`；品目内多个包装去重后 ` · ` 连接（截断 600 字符） |
| `일반명코드(성분명코드)` → 成分表 `일반명` | `product_component` → `variant` | **配方码**（复方一码多行）；品目内多配方码取并集去重（1,472 品目） |
| `함량` + `단위` | `strength_value` / `strength_unit` | 原样存，不换算；简单单位归一（`㎍/μg→mcg`、`I.U→IU`、`KI.U→kIU`、`ml→mL`），**复合单位原样保留** |
| 成分表 `제형` | `dosage_form` / `form_base` / `release` | 韩文剂型 → 站内 form_base；`서방→ER`、`장용→DR`；无成分码的品目 `unknown`（**不臆造**） |
| 成分表 `투여` | `route` | 내복→oral / 주사→injection / 외용→topical；多值取多数（8 品目） |
| `업체명` | `mah` | 多值取多数（6,979 品目，公司更名/合并） |
| `전문일반구분` | `category` | 전문의약품 52,138 / 일반의약품 27,187 / 한약재 13,798 / 원료의약품 339 / 전문,희귀 68 / 의약외품 1 / 空 3,825 |
| `취소일자` | `status` + `note` | 无日期 → `active`（在药价表内）；真实日期 → `unknown` + note「不在表内 ≠ 批文撤销」；`9999-*/8999-*` 占位值 151 品目视为在表；**`status_date` 一律不写** |
| `국제표준코드(ATC코드)` | 只回填 `substance.atc` | 单方 + 7 位完整码且 substance 为空时回填（干跑 600 个）；3–5 位组码不写 |

**成分名对齐**（不做剂量/等效判断）：
1. 显式别名（库内可复核）：`L-menthol→levomenthol`、`S-amlodipine→levamlodipine`、`alpha lipoic acid→lipoic acid`、`alpha amylase→amylase`；
2. 希腊字母展开（`γ→gamma`、`β→beta`、`α→alpha`）+ 反复去立体化学前缀（`dl-`/`l-`/`d-`/`s-`）；
3. 复用 NO 窗口的通用规则：精确 → 去括号（`pancreatin (장용부)` 按括号外对齐，**韩文製剂部位说明不入库**）→ 去 `ion` → 去盐母体（元素母体有 guard）→ INN/BAN 别名；
4. 词序无关（`aluminum magnesium silicate` ↔ `magnesium aluminum silicate`）；
5. 仍对不上：英文名 → 新建 substance（`name_lang='en'`）；纯韩文名 → 新建 substance（`name_lang='other'`，id `kr-<sha1 前 10>`，避免 slug 丢字撞名）。

**名字只挂 trade（상품명），不挂 INN 名字**：KR 成分名大量带盐（`amikacin sulfate` 等），而库内既有「母体/盐」两行 substance 已在别的市场挂同名键；再挂 INN 会把 **+8k 个同名键推成 severe 假警示**（实测：挂 INN 时 severe 增量 8,369，不挂时 8,316——见 §5）。跨市场对应走 substance 层，与 CZ / JP / FR 口径一致。

## 4 干跑计划数字（`--dry-run`，只读现库）

| 指标 | 数值 |
|---|---|
| 品目 → product | **97,356 / 97,356** |
| 商品名（trade 行 / 唯一名） | 110,178 / 109,231（写入去重后 `product_name` 109,496；同品目内归一后同键的写法只在 `name_variant` 保留原文） |
| 成分行 | **117,500**（含量数值全部可解析；单位：exact 105,798 / composite 11,185 / ratio 32 / keep 473 / empty 12） |
| 有成分品目 / 无成分品目 | **50,533（51.9%）** / **46,823（48.1%，无成分码，留空计数）** |
| 成分映射（既有主档） | **94,915 = 80.8%**：exact 69,944 · salt 15,469 · paren 8,756 · kr_alias 412 · tokens 253 · spelling 55 · inn_alias 26 |
| 新建成分行 / 新 substance | 22,585（英文 22,268 / 韩文 317） / **2,547** 个 substance |
| 既有 substance 但无 variant | 10 个（写入时补 base variant，不猜盐型） |
| 包装覆盖 | **93,779 = 96.3%**（3,577 个品目只有「없음」或空包装行） |
| 剂型覆盖 | 结构化 **50,527 = 51.9%**；form_base：unknown 46,829 / tablet 27,100 / capsule 9,203 / injection 6,996 / topical 2,696 / liquid 2,263 / ophthalmic 1,176 / powder 637 / inhalation 319 / suppository 67 / pill 37 / implant 12 / other 21 |
| 释放机制 | ER/DR 由 `서방/장용` 剂型推导（如 서방형정제→ER、장용정제→DR） |
| 途径 / MAH / category | 有途径 50,533（多值 8） / MAH 97,356（100%） / category 93,531（多值 0） |
| ATC | 68,939 = 70.8%（7 位完整码 49,996 品目；单方 7 位可回填 25,884） |
| 状态 | active **65,086** / unknown **32,270**；`status_date` 全空 |
| 单位 | exact 105,798（90.0%）· composite 11,185 原样保留（含括号浓度）· ratio 32 · keep 473 · empty 12 |
| 多值提醒 | 多配方码 1,472 品目 · 多剂型 28 · 多途径 8 · MAH 多值 6,979 |
| 配方码缺失 | 70 个码在成分表缺失（128 行 / 69 品目，其中 62 品目全部码缺失） |

## 5 干跑库验收（`.tmp/kr_dryrun.db` 副本，**未动主库**）

| 表 | before | after | Δ |
|---|---:|---:|---:|
| `product` | 633,722 | **731,078** | +97,356 |
| `product_name` | 833,089 | **942,585** | +109,496（trade 109,496；名行去重后） |
| `product_component` | 804,845 | **922,345** | +117,500 |
| `substance` | 14,006 | **16,550** | +2,544（新建 2,547，3 个按 inn_en 已存在） |
| `variant` | 15,609 | **18,163** | +2,554（2,544 新成分 + 10 个既有成分补 base variant） |
| `name_key` / `name_variant` | 263,427 / 306,931 | **369,829 / 416,162** | +106,402 / +109,231 |
| `source` / `ingest_run` | 47 / 25 | **48 / 26** | `hira_kr_medprice` / `hira_kr_medprice-2026-11-22` |

- `coverage` KR：**('KR', 97,356, 4,686, 65,086, '2026-11-22')**。
- `db/check_data.py --db .tmp/kr_dryrun.db` → **exit 0**；`foreign_key_check` **0**；`quick_check` **ok**（本轮给 `db/check_data.py` 加了 `--db` 参数，默认不变）。
- 回滚演练：`--rollback --db .tmp/kr_dryrun.db --manifest …` → **10 张表逐表差异 0**（含为既有成分补建的 10 个 variant；为此在 `etl/markets/_ingest_common.py` 的 rollback 里加了「只删仍未被引用的 created_variants_for_existing_substances」）。
- 碰撞视图（自动推导，未手工标注）：`severe` 29,617 → **37,933（+8,316）**、`warning` 978 → **1,110（+132）**。原因：韩国**同一商品名被不同 품목 使用且成分集合不同**（例：`60초테이스트겔` 一份 map 到 phosphoric acid、另一份 sodium fluoride；大量 `…주N호` 复方注射剂成分表略有差异）。这是数据事实，不是 NO 那种「母体/盐主档拆分」为主；**建议后续单独审一轮 KR 同名项**，本任务不手工改 `collision`。

## 6 已知缺口（页面口径必须写清）

1. **不是注册库全量**：HIRA 약가마스터 是**医保药价清单**；不能写「韩国全部上市/获批药品」。
2. **无 허가번호**：`approval_id` 存的是 **`품목기준코드`（MFDS 品目码，97,356 唯一）**，页面须标「品目码，非批准号」；HIRA 无审批号、无批文有效期。
3. **`취소일자` ≠ 批文撤销**：有真实취소일자 → `status='unknown'`，note 写「不在药价表内 ≠ 撤销，也 ≠ 停售」；`status_date` 不写（避免被读成撤销日）；9999 占位值 151 品目按在表处理。
4. **成分覆盖 52.0% 品目**：46,823 个品目无成分码，**如实留空**并在 note 写「HIRA 无成分码（覆盖 52.0%…）」；70 个配方码在成分表缺失（128 行）。
5. **剂型覆盖 51.9%**：只用品目内成分表的 `제형`；无成分码的品目 `dosage_form='unknown'`、`form_base='unknown'`，**不从 `제형구분`（정/개/포/바이알 等是包装单位标签）臆造剂型**。
6. **复合单位 11,185 行原样保留**（如 `mg(0.3mg/mL)`，含括号浓度）；只归一简单单位，不换算、不拆浓度。
7. **韩文成分名 317 成分行**新建 `name_lang='other'` 主档（跨市场对齐只对英文名有效）。
8. **品目多值**：MAH 6,979（公司更名/合并，取最多）、剂型 28、途径 8、多配方码 1,472（成分取并集去重）。
9. 不存价格、不转载说明书正文、不做剂量换算/替代推荐；不做「按허가번호查韩国」。
10. 回滚清单约 **28 MB**（97,356 product_id + 106k name_key + 109k name_variant），按「data/sources 只放小快照」口径放 **`data/raw/kr/kr_ingest_manifest_20261122.json`（gitignored，不入库）**，报告只记路径/校验值。

## 7 写库窗口 checklist（等 Lead 消息后执行）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 1) 备份（唯一写库窗口；先确认无其它写入/build）
Copy-Item data\drugs.db data\backups\drugs-YYYYMMDD-HHMMSS-kr.db
& $py -c "import hashlib;print(hashlib.sha256(open(r'data\backups\drugs-...-kr.db','rb').read()).hexdigest())"
# 2) 写库（schema 已含 KR，无需 init_db 重建；先备份再 apply）
& $py etl/ingest_kr.py --apply --allow-real --db data\drugs.db
# 3) 验收
& $py db/check_data.py                       # exit 0 + FK 0
& $py -m unittest discover -s etl -t etl     # 104 tests OK（含 test_ingest_kr）
& $py -m unittest discover -s lib -t lib     # 71 tests OK
# 4) 现查 before→after 与覆盖率，补完本报告 §5/§8
```

写库后预期（干跑实测，主库基线 633,722）：`product 731,078`、`product_name 942,585`、`product_component 922,345`、`substance 16,550`、`variant 18,163`、`coverage KR (97,356 / 4,686 / 65,086)`。

## 8 产物与仓库边界

| 产物 | 路径 | 是否入库 |
|---|---|---|
| 原始 CSV（2 份） | `data/raw/kr/20261122/*.csv`（59.6 MB） | 否（`data/raw/` gitignored） |
| 抓取 manifest | `data/raw/kr/fetch_meta.json`（1,619 B） | 否 |
| 回滚 manifest | `data/raw/kr/kr_ingest_manifest_20261122.json`（预期 ~28 MB） | 否（大文件，按口径放 raw） |
| ETL / 测试 | `etl/ingest_kr.py`、`etl/test_ingest_kr.py` | 是 |
| 体检脚本参数 | `db/check_data.py --db`（默认路径不变） | 是 |
| 共享回滚增强 | `etl/markets/_ingest_common.py`（可选字段，向后兼容） | 是 |

## 9 未做声明

- **未写 `data/drugs.db`**（现库仍 633,722、KR 0 行）；未跑 `run_all.py`；未改 `site/`、未改 `data/markets.json`（frontend 负责）、未动 `db/schema.sql`（KR 枚举已存在）；未 commit、未发布。
- 未新增 `data/sources/` 快照（本市场无小快照需求；回滚清单在 raw）。

_等 Lead 发「KR 写库窗口开放」后按 §7 执行并补完本报告。_
