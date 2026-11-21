# 韩国 KR（HIRA 약가마스터）入库报告 —— v1.2.0（窗口前干跑 + 2026-11-22 写库）

- 日期：2026-11-22（北京时间）｜工位：backend｜任务：`task-8`（T8，P1）
- 状态：**已入库 `data/drugs.db`（2026-11-22 写库窗口，v1.1.1 发布期间）**；窗口前干跑只在副本上做，副本已演练「写库 → check_data → 回滚」并回到基线。
- 写库前备份：`data/backups/drugs-20261121-114732-kr.db`（823,312,384 B，sha256 `1989bd39…3720a2`）；回滚清单：`data/raw/kr/kr_ingest_manifest_20261122.json`（28,351,247 B，gitignored）。
- 依据：`reports/2026-11-22-kr-license-assessment.md`（data-scout，2026-11-22）候选 B = data.go.kr **15067462**（표준코드）+ **15067461**（주성분）。
- 口径（页面文案由 frontend 负责，本报告只给数据与缺口）：**HIRA 약가마스터 是医保药价清单（급여 목록），不是韩国注册库全量**；`취소일자` 只表示「不在药价表内」，**不等于批文撤销**；HIRA **没有 허가번호**。

## 0 结论先行

| 项 | 结果 |
|---|---|
| 快照 | 两份官方 CSV 已在 `data/raw/kr/20261122/`（data-scout 2026-11-22 落盘），本轮**校验复用、未重复下载**；`data/raw/kr/fetch_meta.json` 已写 URL / 时间 / 大小 / sha256 / 行数 |
| 条数 | 표준코드 **309,889 行 / 97,356 品目 / 109,231 唯一商品名**；주성분 **60,750 行 / 20,465 配方码** |
| 入库 | **97,356 个 product**（一行 = 一个品目）；**117,500 个成分行**（含含量）；**109,496 条 `product_name`**（110,178 条名行去重后） |
| 成分映射 | **94,915 / 117,500 = 80.8%** 落到既有 substance 主档；新建 **2,547** 个 substance（英文 22,268 成分行 / 韩文 317 成分行） |
| 覆盖率 | 包装 **93,779 / 97,356 = 96.3%**；剂型结构化 **50,527 = 51.9%**（无成分码的品目不臆造剂型）；MAH **100%**；ATC **68,939 = 70.8%** |
| 状态 | `active`（在药价表内）**65,086**；`unknown`（有真实취소일자，**不判撤销**）**32,270** |
| 主库 before→after | `product` 633,722 → **731,078**（+97,356）；`product_name` 833,089 → **942,585**；`product_component` 804,845 → **922,345**；`substance` 14,006 → **16,550**；`variant` 15,609 → **18,163** |
| 校验 | `db/check_data.py` **exit 0**、`foreign_key_check` **0**、`quick_check` **ok**；副本回滚**逐表差异 0** |
| schema | `country` 枚举**已含 KR**（v0.11.3 枚举先行）；`init_db` 对现库 **no-op**，**不需要重建 product 表** |
| 卡点 | 无（写库已完成；`tests/test_markets_registry.py` 的 KR 注册由 frontend 同窗口处理） |

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

## 5 写库结果与验收（2026-11-22 窗口，**已入主库 `data/drugs.db`**）

窗口前在 `.tmp/kr_dryrun.db` 副本上先演练过同一套「写库 → check_data → 回滚」，实测数字与正式写库完全一致；下表为**正式写库**的结果。

| 表 | before | after | Δ |
|---|---:|---:|---:|
| `product` | 633,722 | **731,078** | +97,356 |
| `product_name` | 833,089 | **942,585** | +109,496（trade 109,496；名行去重后） |
| `product_component` | 804,845 | **922,345** | +117,500 |
| `substance` | 14,006 | **16,550** | +2,544（新建 2,547，3 个按 inn_en 已存在） |
| `variant` | 15,609 | **18,163** | +2,554（2,544 新成分 + 10 个既有成分补 base variant） |
| `name_key` / `name_variant` | 263,427 / 306,931 | **369,829 / 416,162** | +106,402 / +109,231 |
| `source` / `ingest_run` | 47 / 25 | **48 / 26** | `hira_kr_medprice` / `hira_kr_medprice-2026-11-22` |

- `coverage` KR：**('KR', 97,356, 4,686, 65,086, '2026-11-22')**；`source` 行 license=`공공누리 제1유형 (KOGL Type 1)`、`data_as_of=2026-08-31`。
- `db/check_data.py` → **exit 0**；`foreign_key_check` **0**；`quick_check` **ok**（本轮给 `db/check_data.py` 加了 `--db` 参数，默认不变）。
- 回滚演练（写后复制真库到 `.tmp/kr_rollback_check.db` 再 `--rollback`）→ **10 张表逐表差异 0**（含为既有成分补建的 10 个 variant；副本已删）。
- 写库 DB sha256：`1989bd39…` → `76145cca…`；备份 `data/backups/drugs-20261121-114732-kr.db`（sha256 `1989bd39…3720a2`）。
- 碰撞视图（自动推导，未手工标注）：`severe` 29,617 → **37,933（+8,316）**、`warning` 978 → **1,110（+132）**。**归类（本轮复核，与初稿不同）**：
  - **8,302 / 8,316 = 99.8% 是「同一复方组成」的键**（8,302 个都是 2 成分复方）：`collision` 视图对「≤2 成分」的组合按 `severe` 计，是**既有视图口径**——现库 29,617 个 severe 里 **25,256（85.3%）** 也是同一类，KR 只是把韩国大量 2 成分复方的商品名带进来，**不是「同名不同药」**。
  - **只有 14 个键是真·同名不同组成**（逐条列在 §5.1），其中约一半是**拼写/盐型重复主档**（`galamine` vs `gallamine`、`sertacozole` vs `sertaconazole`、`tramadol` vs `tramadol hydrochloride`、`naproxen` vs `naproxen sodium` 等），另一半是真实不同配方。
  - **0 个新增键涉及非 KR 产品**（已逐键核对）→ **不是** NO 那种「跨国母体/盐主档拆分」；不手工改视图，建议后续单独做「成分主档拼写去重 + 2 成分复方碰撞口径复核」。

### 5.1 14 个真·同名不同组成的键（KR 内部）

| 商品名（NFC） | 品目 1 | 品目 2 |
|---|---|---|
| 갈라드주 | Gallamine Triethiodide | galamine triethiodide（拼写重复） |
| 넥스펜정 | Acetaminophen + Domperidone Maleate | Acetaminophen + Fursultiamine |
| 더모메디크림(세르타코나졸질산염) | Sertaconazole | sertacozole nitrate（拼写重复） |
| 동인당태고지1%액(알킬디아미노에틸글리신염산염액) | alkyldiaminoethylglycine hydrochloride | alkyldiaminoethylglycine |
| 란사톤캡슐15mg(란소프라졸과립) | Lansoprazole | lansoprazole granule（重复主档） |
| 리피션엠시티10%주 | MCT 5% + Soybean Oil | MCT 10% + Soybean Oil |
| 명문나프록센정 | Naproxen | Naproxen Sodium（盐型） |
| 목사멘틴듀오시럽(아목시실린.클라불란산칼륨(7:1)) | Amoxicillin Sodium + Potassium Clavulanate | Amoxicillin + Potassium Clavulanate |
| 비스펜틴조절방출캡슐10mg(메틸페니데이트염산염) | Methylphenidate | Methylphenidate Hydrochloride |
| 알비코정 | Cetirizine + Pseudoephedrine HCl | Pseudoephedrine HCl + Triprolidine |
| 토코마연질캡슐 | Magnesium Oxide + Tocopherol | Garlic Oil + Tocopherol |
| 트라콤정 | Acetaminophen + Tramadol | Acetaminophen + Tramadol HCl |
| 헥시타놀0.5%액 | Chlorhexidine Gluconate + Ethanol | Chlorhexidine Gluconate + isopropanol |
| 홀로덤(자기유래피부각질세포) | 불활화백일해균선모적혈구응집소 | autologous keratinocytes |

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

## 7 写库窗口执行清单（**2026-11-22 已执行完毕**；实际结果见 §5）

> 备份 `data/backups/drugs-20261121-114732-kr.db`（sha256 `1989bd39…3720a2`）→ `--apply --allow-real`（43.8 s）→ 校验/回滚演练全部通过；以下命令留作下次重跑记录。

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$bak = "data\backups\drugs-$stamp-kr.db"
$manifest = "data\raw\kr\kr_ingest_manifest_20261122.json"

# 0) 窗口守卫：确认没有 python/rclone/build 在跑、没有其它写库任务
Get-Process python,rclone -ErrorAction SilentlyContinue
# 1) 备份 + 记录哈希（写库前唯一动作）
Copy-Item data\drugs.db $bak -Force
& $py -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" $bak
# 2) 写库（schema 已含 KR，init_db 是 no-op，无需重建 product 表）
& $py etl/ingest_kr.py --apply --allow-real --db data\drugs.db --manifest $manifest
# 3) 体检 + 测试
& $py db/check_data.py                       # 期望 exit 0
& $py -m unittest discover -s etl -t etl     # 期望 OK（CZ 基线需先按 §10 改）
& $py -m unittest discover -s lib -t lib     # 期望 OK
& $py lib/markets.py --check                 # 期望 OK（source 行已写）
# 4) 现查 before→after / 覆盖率 / 回滚演练，补完本报告
```

**校验 SQL（写库前记 before、写库后记 after，数字进报告）**

```sql
-- 表级 before→after（同一组 SQL 前后各跑一次）
SELECT COUNT(*) FROM product;                                   -- 期望 633,722 → 731,078
SELECT COUNT(*) FROM product WHERE country='KR';                -- 期望 0 → 97,356
SELECT COUNT(*) FROM product_name;                              -- 期望 833,089 → 942,585
SELECT COUNT(*) FROM product_component;                         -- 期望 804,845 → 922,345
SELECT COUNT(*) FROM substance;                                -- 期望 14,006 → 16,550
SELECT COUNT(*) FROM variant;                                  -- 期望 15,609 → 18,163
SELECT COUNT(*) FROM name_key;                                 -- 期望 263,427 → 369,829
SELECT COUNT(*) FROM name_variant;                             -- 期望 306,931 → 416,162
-- 覆盖率（KR）
SELECT COUNT(*) FROM product WHERE country='KR' AND pack IS NOT NULL AND pack<>'';
SELECT COUNT(DISTINCT pc.product_id) FROM product_component pc JOIN product p USING(product_id)
 WHERE p.country='KR' AND pc.strength_value IS NOT NULL;       -- 50,533
SELECT COUNT(*) FROM product_component pc JOIN product p USING(product_id)
 WHERE p.country='KR' AND pc.strength_value IS NOT NULL;       -- 117,500
SELECT COUNT(*) FROM product WHERE country='KR'
 AND (form_base IS NULL OR form_base IN ('other','unknown'));  -- 46,850（无成分码不臆造）
SELECT status, COUNT(*) FROM product WHERE country='KR' GROUP BY 1;  -- active 65,086 / unknown 32,270
SELECT COUNT(*) FROM product WHERE country='KR' AND approval_id IS NULL;  -- 0（= 품목기준코드）
-- 完整性与护栏
PRAGMA foreign_key_check;      -- 0 行
PRAGMA quick_check;            -- ok
SELECT * FROM coverage WHERE country='KR';
SELECT * FROM source WHERE source_id='hira_kr_medprice';
SELECT * FROM ingest_run WHERE source_id='hira_kr_medprice';
```

**回滚演练（必须做；写库后对副本回滚，不动真库）**

```powershell
Copy-Item data\drugs.db .tmp\kr_rollback_check.db -Force
& $py etl/ingest_kr.py --rollback --db .tmp\kr_rollback_check.db --manifest data\raw\kr\kr_ingest_manifest_20261122.json
# 期望：10 张表 diff_vs_counts_before 全 0（含为既有成分补建的 10 个 variant）
Remove-Item .tmp\kr_rollback_check.db
```

写库后预期（干跑实测，主库基线 633,722）：`product 731,078`、`product_name 942,585`、`product_component 922,345`、`substance 16,550`、`variant 18,163`、`coverage KR (97,356 / 4,686 / 65,086)`。

## 8 产物与仓库边界

| 产物 | 路径 | 是否入库 |
|---|---|---|
| 原始 CSV（2 份） | `data/raw/kr/20261122/*.csv`（59.6 MB） | 否（`data/raw/` gitignored） |
| 抓取 manifest | `data/raw/kr/fetch_meta.json`（1,619 B） | 否 |
| 回滚 manifest | `data/raw/kr/kr_ingest_manifest_20261122.json`（**28,351,247 B**） | 否（大文件，按口径放 raw） |
| DB 备份（写库前） | `data/backups/drugs-20261121-114732-kr.db`（823,312,384 B） | 否（gitignored） |
| ETL / 测试 | `etl/ingest_kr.py`、`etl/test_ingest_kr.py` | 是 |
| 体检脚本参数 | `db/check_data.py --db`（默认路径不变） | 是 |
| 共享回滚增强 | `etl/markets/_ingest_common.py`（可选字段，向后兼容） | 是 |

## 9 完成声明

- **已写 `data/drugs.db`**（2026-11-22 窗口；`product` 731,078、KR 97,356）；写库前备份 + 写后副本回滚演练均已做（§5）。
- 未跑 `run_all.py`；未改 `site/`、未改 `data/markets.json`（frontend 负责）、未动 `db/schema.sql`（KR 枚举已存在）；未 commit、未发布。
- 未新增 `data/sources/` 快照（本市场无小快照需求；回滚清单在 raw）。

## 10 写库后测试 / 门禁预判（同窗口一次改完，别再来一轮 CI 12/13）

**实测方法**：窗口前把 KR 全量 `--apply` 到副本 `.tmp/kr_probe.db`（主库只读），在副本上跑 `tests/trilingual/run_tests.py`（`DB` 指向副本）、`lib/search.py` 与各断言口径；数字均为副本现查。**2026-11-22 窗口执行结果：#1/#2/#3 已按表改完，`tests.test_lib_atc_category` 22 OK、`etl` 104 OK、`lib` 71 OK；#4 由 frontend 同窗口处理；#8 已在副本复核。**

| # | 文件 / 门禁 | 用例 | 现期望 | KR 后实际（需改） |
|---|---|---|---|---|
| 1 | `tests/test_lib_atc_category.py` | `test_colloquial_acceptance_words`（12 词中 4 词变） | 降糖药 `Metformin`；减肥药 `Semaglutide`；他汀 `Atorvastatin`；抗抑郁药 `Duloxetine` | **降糖药 `Metformin Hydrochloride`**（3,941 > Metformin 2,961；首卡 CZ `SITAGLIPTIN/METFORMIN +PHARM` 成分含它）· **减肥药 `Orlistat`**（361 > 353）· **他汀 `Rosuvastatin`**（首卡 LV `ROSUVASTATIN TEVA PHARMA`；Rosuvastatin Calcium 2,053 / 基名 1,463 > Atorvastatin 1,914）· **抗抑郁药 `Escitalopram`**（Escitalopram Oxalate 974 > Duloxetine 874；首卡 ES `ESCITALOPRAM` 显示基名） |
| 2 | 同上 | `test_category_top1_by_ingredient_total`（3 例中 1 例变） | 抗抑鬱藥 `Duloxetine` | **`Escitalopram`**（同上；这是对 v1.1.0 那次 Duloxetine 改动的**回退**，需在 docstring 写 v1.2.0 窗口数字） |
| 3 | `etl/test_ingest_cz.py` | `test_rerun_keeps_cz_no_component_at_1409` | 常量 1409 / 67172 / 91015 / skipped 1406 | **1268 / 67313 / 91184 / 1265**（KR 新增 2,544 个 substance 让 CZ 重跑计划多映射 141 个产品 / 169 个成分行；`CZ_DB_*` 1424/67157/90981 不变，比较仍用 ≤/≥）→ 方法名已改为 `_at_1268`（已改并全绿） |
| 4 | `tests/test_markets_registry.py` | `TestMarkets.test_enabled_markets_match_db_countries` | DB 国家集合 == `country_order`（16） | **必翻**：DB 变 17 国（含 KR）。两种收口只能二选一：① frontend 同窗口在 `data/markets.json` 注册 KR（`source_id=hira_kr_medprice`、`enabled=true`、`ui_language_gaps=["ko"]`）；② 若只写库不注册，则该用例红。**建议①** |
| 4b | 同上（注册 KR 后连带要改） | `test_registered_market_set`（硬编码 16 国集合）· `test_i18n_keys_unique_and_match_existing_site_keys` / `test_enabled_market_sources_exist_in_db`（`SITE_COUNTRY_I18N` + `home.kr`）· `TestUiLanguageCoverage.test_every_enabled_market_declares_both_fields` / `test_gaps_match_native_language`（`MARKET_NATIVE_LANGS["KR"]=("ko",)`） | 16 国常量 + `home.kr` 不存在 | 需 frontend 同批：`data/markets.json` KR 条目 + `site/build.py` 九语 `home.kr` 文案 + 上述测试常量；DB 侧 `source` 行已由 ingest 写入 |
| 5 | `deploy/ci_checks.py` → `unittest:etl` | 整包 | PASS（104） | 已转绿：仅 #3 一处常量；104 OK |
| 6 | `deploy/ci_checks.py` → `unittest:lib-atc-category`（全量模式） | 整模块 | PASS（22） | 已转绿：#1/#2 共 5 处期望；`CategoryMatchTest`（快模式）不受影响 |
| 7 | `deploy/ci_checks.py` → `unittest:lib` / `unittest:mobile` | 整包 | PASS（71 / 通过） | **不受影响**：lib 用例多用临时 fixture DB；`RealDbAliasTests` 的 dextrose/葡萄糖/lipitor 三条在副本上复跑通过 |
| 8 | `deploy/ci_checks.py` → `trilingual` | `run_tests.py` 78 案例 | 78 案例 / 75 通过；3 个 `ALLOWED_TRILINGUAL_FAILURES`（metformin/combo、beclometasone/dup_inn、chlorphenamine/dup_inn） | **无新增失败**：副本实测 78/75、Top-5 98.9% / Top-1 96.4%、跨国 78/78；3 个 fail 全在 allowed 表 → PASS（基线 78/74） |
| 9 | `deploy/ci_checks.py` → `database` | `db/check_data.py` | PASS | 副本 **exit 0**、FK 0、quick ok → PASS |
| 10 | `deploy/ci_checks.py` → `dist-integrity` / `ui-surface` / `first_screen_check` | 发布产物 | PASS | 由 release 重建后复测；**注意 `data/idx/core.json` 会因 +106,402 个 name_key（韩文键）增大**，release 需按 gzip 2.5–12 MB / raw 11–50 MB 护栏复测 |
| 11 | `tests/trilingual/cases_v2/v3/v4.json` + `run_cases_v2.py` | 生成式用例 | — | **不在 CI**（CI 只跑 `run_tests.py`）；查询均为拉丁/中文，韩文商品名（Hangul）不参与匹配 → 不受影响 |

**建议同窗口顺序**：写库（§7）→ 改 #1/#2/#3（backend）→ 改 #4 系列（frontend + Lead 拍板 KR 注册）→ 跑 `unittest etl` / `lib` / `tests.test_lib_atc_category` / `tests.test_markets_registry` / `trilingual` → 交 release 重建 + 全量 CI。

_等 Lead 发「KR 写库窗口开放」后按 §7 执行并补完本报告。_
