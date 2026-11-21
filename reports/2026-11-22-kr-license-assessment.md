# 韩国（KR）药品产品级数据——再发布许可与数据可得性评估（v1.2.0 前置）

- 日期：2026-11-22（北京时间）｜工位：data-scout｜任务：`task-6`（T6，P0）
- 背景：用户 2026-11-22 02:10 定 **v1.2.0 = 韩国市场**；本任务只做**许可与可得性**，**不写库**（入库由 backend 在获批后另派）。
- **只读声明**：未注册、未登录、未提交表单、未发信、未伪装 UA、未绕 WAF、未写 `data/drugs.db`、未改 `site/` / `etl/` / `deploy/`、未 commit、未发布。只做了匿名 GET/HEAD/POST（POST 仅为复现页面自身的下载 AJAX，见 §2.4）与两份**官方明示「免登录下载」**的文件数据落盘（`data/raw/kr/20261122/`，不入库）。
- **一句话结论**：**KR 有两条路，许可都不是卡点，账号是**——
  **A（字段最全，需人 10 分钟）**：`data.go.kr` 数据集 **15095677**（MFDS 의약품 제품 허가정보）许可原文为「**이용허락범위 제한 없음**」，`무료`、`실시간`、REST；但 API 必须 `serviceKey`（无 key 实测 **HTTP 401**），而门户注册**只面向内国人与国税厅登记事业者**、第 4 步「본인인증」不可跳过（**기업회원 也是 6 步、第 4 步仍是 본인인증**）→ **「SMC 有没有韩国事业者登录号」并不能解决卡点**。
  **B（今天就能入库，无人阻塞）**：`data.go.kr` 的 **HIRA 약가마스터** 两个**文件数据**（15067462 标准码 + 15067461 主成分），许可 **공공저작물 제1유형（出处标示；可商用、可演绎）**，页面明示「**파일데이터는 로그인 없이 다운로드**」，实测匿名拉到 **309,889 行 / 97,356 品目 / 109,231 商品名**；**唯一硬伤：成分码只覆盖 52.0% 品目（西药 63.7%）**，其余按数据纪律丢弃计数。

## 0 需人（决策 / 邮箱）

1. **【阻塞 Route A，推荐先做，约 10 分钟】** 找一位**韩国籍**朋友（或有韩国手机号/공동인증서 的同事）用**本人实名**登录 `data.go.kr`，对数据集 `15095677` 点「**활용신청**」→ 开发阶段**自动승인**（10,000 次/日）→ 把 `Encoding 인증키` 交给 Lead（**只进 `.env`**，不进仓库/报告/对话以外的文档）；或直接从 `data.mfds.go.kr` 下载「의약품 제품 허가정보」CSV 交给本站（许可同为「利用许可范围无限制」）。
   - **不需要** SMC 的韩国事业者登录号——기업회원 第 4 步仍需个人 본인인증，绕不过去（§2.3 原文）。
2. **【不阻塞，需批准】** 是否**先按 Route B 起步**（HIRA 两份 KOGL 제1유형 文件，匿名可下，成分覆盖 52%）——批了 backend 就能立刻排写库窗口，不必等任何人。**建议批**：v1.2.0 不必空等。
3. **【邮箱登录态】** 若走人工书面确认（§8 申请信），发信需 SMC 邮箱登录态（LG14 口径），**本轮只起草、未发**。

## 1 结论先行

| 问题 | 答案 |
|---|---|
| 许可允许再发布吗？ | **允许**。15095677 的许可字段原文 = **「이용허락범위 제한 없음」**（英文页 `Scope of License` = **`The use permission range limitless`**）；DCAT 机器可读 `<dct:rights>이용허락범위 제한 없음</dct:rights>`；未挂 공공누리 标识，按门户政策页解释等同「自由利用」（可商用、可演绎、无强制出处义务；本站仍署名） |
| 免账号吗？ | **API 不免**（无 key → **HTTP 401**）；**文件数据免**（页面原文「파일데이터는 로그인 없이 다운로드를 통해 이용하실 수 있습니다」，实测匿名 HTTP 200 / `attachment`） |
| 非韩国人能注册吗？ | **不能**。`auth.data.go.kr/sso/common-signup` 只有 일반회원（만 14세 이상 **내국인**）/ 어린이 회원（내국인）/ 기업회원（**국세청에 등록된 사업자**）；全文 `FOREIGN` / `외국` / `여권` / `passport` / `재외` 命中 **0**；第 4 步 `본인인증`（5 步/6 步两种流程都有） |
| 批量形态 | ① **REST OpenAPI**（JSON+XML，3 个操作，分页 `pageNo/numOfRows`，需 key）；② **CSV 文件数据**（data.go.kr 上的 HIRA 两份，匿名额；MFDS 自家 CSV 在 `data.mfds.go.kr` 仍需登录） |
| 实测条数 | **15095677 拿不到行**（401）→ 条数只能等 key；**HIRA 文件实测：309,889 行包装级 / 97,356 品目 / 109,231 唯一商品名**（另 60,750 行成分主数据） |
| 字段（本站需要的 7 项） | **API**：7/7 齐（商品名·成分·含量·剂型·规格·MAH·注册号·状态；成分/含量在**第 3 个操作**）｜**HIRA 文件**：商品名 ✅、规格 ✅（`약품규격` 100%）、剂型 82.1%（品目级）、MAH ✅、注册号 ✅（`품목기준코드`）、状态 ✅（`취소일자`，语义待确认）、**成分 ❌ 仅 52.0%** |
| 更新频率 | 15095677 **실시간**（页面 수정일 2026-09-18）；HIRA 标准码 **分기**（基准 2026-08-31）、主成分 **연간**（2026-11-05） |
| 卡点 | **只有账号**（본인인증 = 韩国实名）。许可不是卡点、字段不是卡点、付费也不是（免费） |
| 入库成本 | Route A：**6–9 人时**（3 操作分页 + join + 文档字段剔除）；Route B：**4–6 人时**（2 个 CP949 CSV + 成分码 join + 规格正则 + 丢弃计数） |

## 2 许可与账号证据（2026-11-22 抓取，原文短引）

### 2.1 数据集级许可：15095677

| # | 证据 | 原文短引 | 判定 |
|---|---|---|---|
| 1 | 数据集页（韩）<https://www.data.go.kr/data/15095677/openapi.do> | OpenAPI 명「식품의약품안전처_의약품 제품 허가정보」；제공기관 식품의약품안전처 / 관리부서 데이터혁신기획팀 / 043-719-1627；등록일 2021-12-08、**수정일 2026-09-18**、활용신청 수 **10,253** | 官方数据集（HTTP 200，223,104 B） |
| 2 | 同上「이용 조건 및 라이선스 정보」 | **비용부과유무 = 무료**；**업데이트 주기 = 실시간**；**이용허락범위 = 「이용허락범위 제한 없음」**（链 <https://www.data.go.kr/ugs/selectPortalPolicyView.do>）；심의유형 = 개발단계 **자동승인** / 운영단계 **심의승인**；신청 가능 트래픽 = 개발계정 **10,000**（운영계정은 활용사례 등록 후 증액） | **许可不是卡点** |
| 3 | 英文页 <https://www.data.go.kr/en/data/15095677/openapi.do> | `Payment` = **Free**；`Update Cycle` = **Real-time**；**`Scope of License` = `The use permission range limitless`**；`Review Type` = `Manual Review`（94,497 B） | 与韩文一致 |
| 4 | DCAT（机器可读）<https://www.data.go.kr/biz/dcat/metadata/15095677.do> | `<dct:rights>이용허락범위 제한 없음</dct:rights>`；`dct:issued 2021-12-08` / `dct:modified 2026-09-18`；`dcat:format JSON+XML`；**无 `dct:license` 元素**（权利写在 `dct:rights`） | 与 CH 相反（CH 是 `dct:license`），此处**权利声明在 rights** |
| 5 | schema.org <https://www.data.go.kr/catalog/15095677/openapi.json> | `"license":{"name":"이용허락범위 제한 없음","url":"https://www.data.go.kr/ugs/selectPortalPolicyView.do"}`；`"isAccessibleForFree":true`；`dateModified 2026-09-18`；`distribution.contentUrl = https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService08` | 机器可读、可引用 |
| 6 | 门户政策页 <https://www.data.go.kr/ugs/selectPortalPolicyView.do> | 「공공데이터포털을 통해 제공 중인 공공데이터는 **별도의 신청절차 없이 이용 가능**하며…」；同时警示「저작권 등 **제3자 권리가 포함된** 공공데이터는 권리자의 정당한 이용허락을 확보해야 합니다」 | 自由利用 + **第三方权利保留**（本站只取事实字段，规避风险） |
| 7 | 门户 이용약관（同页 tab）第 12·14·15 条 | 第12条4项 9)「기타 서비스의 안정적인 운영에 지장을 주거나 줄 우려가 있는 일체의 행위」禁止；第14条5项「오픈 API 방식… 제공기관은 특정 회원의 이용형태로 인해… 업무에 지장… 서비스 이용을 제한할 수 있다」；第15条2项「포털 **자료실** 메뉴에 게시된 정보는 공공데이터 제공결정을 통한 것이 아니며… 권리 침해에 유의」 | **无「禁止再发布数据」条款**；限制针对**滥用/扰民**，不是再发布 |

**判定：🟢 数据本身可再发布**（无出处强制义务，本站仍署名「식품의약품안전처 / data.go.kr」+ 数据截止日 + 标明本站已归一化）。

### 2.2 공공누리（KOGL）类型 1–4 的含义（决定备选源能否用）

来源：门户政策页「참고 2 – 공공누리 유형안내」表（<https://www.data.go.kr/ugs/selectPortalPolicyView.do>；官方 kogl.or.kr 本机不可达，报「无法连接到远程服务器」——不伪 UA、不绕，改用门户副本）：

| 类型 | 条件 | 商用 | 演绎（2차적 저작물） | 对本站含义 |
|---|---|---|---|---|
| **제0유형 자유이용** | **无条件** | ✅ | ✅ | 最宽松；15095677 的「이용허락범위 제한 없음」实质等同此类（门户自有的表述，不等同于挂了 KOGL 标识） |
| **제1유형 출처표시** | 须**标明出处** | ✅ | ✅ | **可入库**（HIRA 两份文件即此型）；页面须署名 + 许可链接 |
| 제2유형 출처표시+상업적 이용금지 | 出处 + 非商业 | ❌ | ✅ | 本站现为非商业公开站 → 可用，但**未来商业化必须重评** |
| 제3유형 출처표시+변경금지 | 出处 + 禁改 | ✅ | ❌ | **与本站冲突**：本站做标准化/归一化属演绎 |
| 제4유형 출처표시+상업적 이용금지+변경금지 | 出处 + 非商业 + 禁改 | ❌ | ❌ | **不可用** |
| （表内另有「AI유형」：无条件、可商用、可演绎） | 面向 AI 训练 | ✅ | ✅ | 与本站无关，仅登记 |

### 2.3 账号：非韩国人无路径（本轮复核，2026-11-22）

`https://www.data.go.kr/uim/login/signupView.do` → `https://auth.data.go.kr/sso/common-signup`（HTTP 200，21,519 B）原文：

> 1단계 회원구분 → 2단계 약관동의 → 3단계 정보입력 → **4단계 본인인증** → 5단계 가입완료
> **일반회원** — 만 14세 이상 **내국인**；**어린이 회원** — 만 14세 미만 **내국인**；**기업회원** — **국세청에 등록된 사업자**

- 全页检索 `FOREIGN|foreign|외국|여권|passport|재외` → **0 命中**（与前两轮 K1/K4 结论一致）。
- **기업회원是 6 步流程**（同页 `corpStep`）：회원구분 → 약관동의 → 정보입력 → **본인인증** → 정보입력(기업) → 가입완료；企业认证入口 `/sso/corp-certify`（HTTP 200，48,598 B）。
  → **即使 SMC 有韩国事业者登录号，第 4 步的「본인인증」仍要一个韩国自然人身份**；这就是「有没有事业者登录号」不是答案的原因。
- **无 key 直调 API 实测**：`GET https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService08/getDrugPrdtPrmsnInq08?pageNo=1&numOfRows=3&type=json` → **HTTP 401 Unauthorized**（响应无正文）。**没有任何「免 key 试调」口子**。

### 2.4 文件数据：官方明示免登录（本轮新证据）

`https://www.data.go.kr/data/15067462/fileData.do` 页面（两处）原文：

> **파일데이터는 로그인 없이 다운로드를 통해 이용하실 수 있습니다.**

实测（匿名、无 cookie）：

```
POST https://www.data.go.kr/tcs/dss/selectFileDataDownload.do
     publicDataPk=15067462&publicDataDetailPk=uddi:8116acc9-…&publicDataTyCode=PR0051
  → 200 JSON {"status":true, "atchFileId":"FILE_000000007666876"}

GET  https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000007666876&fileDetailSn=1
  → 200  Content-Disposition: attachment; filename="건강보험심사평가원_약가마스터_의약품표준코드 2026.08.csv"
       Content-Length: 55,741,167  (CSV, CP949)
```

> 说明：这两步就是页面「다운로드」按钮自己的调用（`script_fileDetail.js` 的 `fn_fileDataDown`），**没有绕过任何登录校验**——门户本身对**文件数据**不设登录闸门，只对 **API 활용신청** 设闸门。`nedrug` 的 `robots.txt` 仍是 `Disallow: /`（26 B），不碰。

## 3 必查 12 项（`docs/数据源调研清单.md` §3）

### 3.1 首选源：data.go.kr `15095677`（MFDS 의약품 제품 허가정보，OpenAPI）

| # | 项 | 结论与证据 |
|---|---|---|
| 1 | 官方入口 | 数据集 <https://www.data.go.kr/data/15095677/openapi.do>（英 <https://www.data.go.kr/en/data/15095677/openapi.do>）；API host `https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService08` |
| 2 | 许可原文 + 名称 | **이용허락범위 제한 없음**（英 `The use permission range limitless`）；政策页 <https://www.data.go.kr/ugs/selectPortalPolicyView.do>；DCAT `dct:rights` 同文本 |
| 3 | 再发布限制 | 允许商用 ✅、允许演绎 ✅、**无强制出处义务**（本站仍署名）；限制条款只见「不得妨碍门户运营」「API 过度使用可被限制」「门户本部资料室内容不适用」 |
| 4 | 是否需账号 | **API：需**（免费注册后「활용신청」，개발단계 자동승인；无 key → 401）。**注册需韩国实名**（内国人/国税厅事业者 + 본인인증）→ **非韩国人无路径** |
| 5 | 批量入口形态 | REST（JSON+XML），**3 个操作**：`/getDrugPrdtPrmsnInq08`（허가 목록，**21 字段**）、`/getDrugPrdtPrmsnDtlInq08`（허가 상세，**44 字段**）、`/getDrugPrdtMcpnDtlInq08`（주성분 상세，**13 字段**）；均支持 `pageNo/numOfRows/type`，可按 `item_name/entp_name/item_seq/atc_code/…` 过滤 |
| 6 | 字段清单 | 见 §4.1（商品名含韩/英双语、成分+含量在 주성분 상세、剂型在 DUR/제형 相关列、MAH `ENTP_NAME`、注册号 `품목기준코드`/`품목허가번호`、状态 `CANCEL_NAME`/`CANCEL_DATE`、`PACK_UNIT`、`ATC_CODE`、`BAR_CODE`） |
| 7 | 条数（实测） | **拿不到**（401）。需 key 后 `totalCount` 现查；**不要照抄任何二手估计** |
| 8 | 更新频率 / 截止 | **실시간**（页面 수정일 2026-09-18；数据本身实时，无固定 cutoff） |
| 9 | 规格与剂型可得性 | **结构化**：剂型在 `상세` 操作（DUR 제형/`전문일반`）/ `주성분` 操作的 `제형`；含量 `QNT`+`INGD_UNIT_CD`（**原样存，不做换算**）。**无需从名称解析** |
| 10 | 署名要求原文 | 无强制署名条款（제0유형 性质）。本站仍写：`출처: 식품의약품안전처, 「의약품 제품 허가정보」, 공공데이터포털(data.go.kr), 이용허락범위 제한 없음, 기준일 YYYY-MM-DD` |
| 11 | 抓取礼貌 | `https://www.data.go.kr/robots.txt` = 177 B，仅对 `Googlebot` 禁若干路径（不含数据集/API 路径）；`apis.data.go.kr/robots.txt` → **400**（未声明）。按「一次性全量分页拉取 + 拉完停用」执行；**不做常驻实时轮询** |
| 12 | 入库成本 / 风险 | **6–9 人时**（3 操作分页 + `ITEM_SEQ` join + 剔除 `EE/UD/NB_DOC_DATA` 说明书正文 + 状态/取消语义）；风险：① 需人拿 key（唯一硬卡点）；② 说明书文档字段必须**不入库**；③ `운영계정` 需**심의승인**，长期调用要走运营审核 |

### 3.2 备选源：data.go.kr `15067462` + `15067461`（HIRA 약가마스터，**文件数据，免登录**）

| # | 项 | 结论与证据 |
|---|---|---|
| 1 | 官方入口 | <https://www.data.go.kr/data/15067462/fileData.do>（표준코드）、<https://www.data.go.kr/data/15067461/fileData.do>（주성분） |
| 2 | 许可原文 + 名称 | **공공저작물 : 출처표시 (제 1유형)**（DCAT `<dct:rights>공공저작물 : 출처표시 (제 1유형)</dct:rights>`；schema.org `license.url = https://www.kogl.or.kr/info/licenseType1.do`） |
| 3 | 再发布限制 | 商用 ✅、演绎 ✅、须出处标示；**与 HIRA 自家门户条款冲突时以门户数据集许可为准**（见 §5 不采用原因） |
| 4 | 是否需账号 | **免账号**（页面原文「파일데이터는 로그인 없이 다운로드를 통해 이용하실 수 있습니다」；实测匿名 200） |
| 5 | 批量入口形态 | CSV（CP949，无 BOM）；표준코드 **55,741,167 B / 22 列 / 309,889 行**，주성분 **3,836,693 B / 8 列 / 60,750 行** |
| 6 | 字段清单 | 见 §4.2：상품명 ✅、약품규격 ✅、제형구분（64.3% 行 / 82.1% 品目）、업체명 ✅、품목기준코드 ✅、품목허가일자、취소일자、ATC、일반명코드（→ 成分名/함량/단위/투여） |
| 7 | 条数（实测） | **309,889 行 / 97,356 品目 / 109,231 唯一商品名 / 173,707「商品名+规格」组合**；成分主数据 **60,750 行 / 20,465 唯一成分码** |
| 8 | 更新频率 / 截止 | 표준코드 **분기**（데이터 기준 2026-08-31，파일명 `…20260831`；수정일 2026-09-17）；주성분 **연간**（2026-11-05） |
| 9 | 规格与剂型可得性 | **规格可解析**：`약품규격` 100% 有值、**仅 4,256 种唯一值**，形态固定为「数字+韩文单位」（`500그램`/`100밀리그램`/`10밀리리터`/`2000IU`/`424Unit`），**无逗号/加号复方串（0%）**；`없음` 33,820 行（10.9%）。剂型 = `제형구분`（品目级 82.1%），缺失集中在 한약재/원료 |
| 10 | 署名要求原文 | 제1유형 = **출처표시**。建议句式：`출처: 건강보험심사평가원, 「약가마스터_의약품표준코드/주성분」(공공데이터포털, 공공누리 제1유형), 기준일 2026-08-31. DrugCrossRef에서 정규화함.` |
| 11 | 抓取礼貌 | 同 §3.1：robots 仅限制 Googlebot 的若干路径；**每个写库窗口下一次（2 个文件，约 60 MB）**，不做轮询 |
| 12 | 入库成本 / 风险 | **4–6 人时**（2 CSV、CP949、按 `일반명코드` join、规格正则、丢弃计数）。**风险**：① **成分码只覆盖 52.0% 品目（西药 63.7%）**，其余必须丢弃 + 计数；② 这是**급여（报销）口径**，不是「全部上市/全部获批」→ 覆盖页不得写「韩国全部药品」；③ `취소일자` 语义 = 급여 목록 삭제 还是 허가 취소 **待确认**（不得直接标「已注销」） |

## 4 字段与实测覆盖率

### 4.1 `15095677` 三个操作的完整字段（来自页面内嵌官方 Swagger，**非实测样例行**——无 key 取不到数据）

| 操作 | 名称 | 字段数 | 关键字段 |
|---|---|---|---|
| `/getDrugPrdtPrmsnInq08` | 의약품 제품 허가 목록 | **21** | `ITEM_NAME` 품목명 · `ITEM_ENG_NAME` 영문제품명 · `ENTP_NAME` 업체명 · `ENTP_ENG_NAME` · `ITEM_PERMIT_DATE` 품목허가일자 · `PRDUCT_PRMISN_NO` 품목허가번호 · `ITEM_INGR_NAME` **주성분（仅名称，无含量）** · `ITEM_INGR_CNT` 주성분수 · `SPCLTY_PBLC` 전문/일반 · `PRDUCT_TYPE` 분류명 · `CANCEL_DATE` 취하일자 · `CANCEL_NAME` 취하구분 · `EDI_CODE` 보험코드 · `BIG_PRDT_IMG_URL` |
| `/getDrugPrdtPrmsnDtlInq08` | 의약품 제품 허가 상세정보 | **44** | `CHART` 성상 · `BAR_CODE` 표준코드 · `MATERIAL_NAME` 원료성분 · `PACK_UNIT` **포장단위** · `STORAGE_METHOD` · `VALID_TERM` · `ATC_CODE` · `MAIN_ITEM_INGR` 유효성분 · `INGR_NAME` 첨가제 · `TOTAL_CONTENT` 총량 · `RARE_DRUG_YN` · `CANCEL_NAME` **상태** · `CANCEL_DATE` · `CHANGE_DATE` · `GBN_NAME` 변경이력 · **`EE_DOC_DATA`/`UD_DOC_DATA`/`NB_DOC_DATA`/`PN_DOC_DATA` 说明书正文（本站不入库）** |
| `/getDrugPrdtMcpnDtlInq08` | 의약품 제품 주성분 상세정보 | **13** | `MTRAL_NM` **원료명（成分名）** · **`QNT` 분량 + `INGD_UNIT_CD` 분량단위 → 含量** · `MAIN_INGR_ENG` 영문성분명 · `CPNT_CTNT_CONT` 세부구성항목 · `ITEM_SEQ` 品目码 · `MTRAL_CODE` 원료코드 · `PRDUCT` 제품명 |

> **关键结构**：**商品名/MAH/注册号/状态在操作 1+2；成分+含量只有操作 3**，按 `ITEM_SEQ` join。**「列表操作没有含量」是最容易低估成本的地方**（要跑 3 个操作才能拼出「成分+含量」）。
> 三者都只有 `serviceKey` 必填，其余可选；分页参数无文档上限（`numOfRows` 为 integer，未标最大值）。

### 4.2 HIRA 文件实测（本轮真跑，CP949 解码）

**`hira_yakga_stdcode_20260831.csv`（15067462）**：22 列 / **309,889 行**

| 字段 | 有值率 | 说明 |
|---|---|---|
| `한글상품명` 商品名（韩） | **100%**（309,889），唯一 **109,231** | 无英文名（英文名只在 MFDS API 有） |
| `업체명` MAH | **100%** | 文本，未规范化（`(유)대효제약` 等） |
| `약품규격` 规格 | **100%**（309,854），唯一 **4,256** | 「数字+韩文单位」；`없음` 33,820 行 |
| `품목기준코드` **注册号等价物** | **100%**，唯一 **97,356** | 与 MFDS 품목기준코드 同源，可做跨源校验 |
| `표준코드`（KD 码） | **100%**，唯一 309,889 | 包装级唯一定位符 |
| `품목허가일자` | **99.8%** | |
| `제형구분` 剂型 | 行 **64.3%** / 品目 **82.1%** | 缺失集中在 한약재/원료 |
| `일반명코드(성분명코드)` **成分码** | 行 **44.4%** / 品目 **52.0%**（西药品目 **63.7%**） | **最大硬伤**；复方：1,018 品目有 2 个码、263 有 3 个、最多 8 个 |
| `취소일자` 状态 | 行 **25.1%** / 品目 **32,421** | 在册品目 **64,935**；在册+注销 = 97,356（两集合不重叠） |
| `국제표준코드(ATC코드)` | 行 **76.8%** / 品目 **70.8%** | |
| `전문일반구분` | 95.5%（전문의약품 165,365 行 / 일반의약품 87,583 / **한약재 41,797** / 원료의약품 1,169） | 한약재占 13.5%，不宜与西药混算 |

**`hira_yakga_ingredient_20261105.csv`（15067461）**：8 列 / **60,750 行** / 唯一 `일반명코드` **20,465**

| 字段 | 有值率 |
|---|---|
| `일반명`（成分名） | **100%** |
| `함량` + `단위` | **100%** / **99.2%** |
| `제형` | **99.5%** |
| `투여`（给药途径） | **100%** |
| `분류번호`（MFDS 分类号） | **100%** |

- **join**：`표준코드.일반명코드(성분명코드) = 주성분.일반명코드`，行级命中 **137,439/309,889 = 44.4%**；品目级 **50,595/97,356 = 52.0%**。
- 样例（原文）：
  - 标准码：`대효갈근 | (유)대효제약 | 500그램 | 기타 | 199905709 | 1999-01-30 | (成分码空) | |`
  - 成分：`100101AGN | GN | 과립제,세립 | 상황균사체엑스 | 421 | 내복 | 1.1 | g`

## 5 备选源并联评估（推荐 / 不采用原因）

| # | 候选源 | 许可 | 免账号批量 | 字段（7 项） | 实测 | 判定 |
|---|---|---|---|---|---|---|
| **A** | **data.go.kr `15095677`** MFDS 의약품 제품 허가정보（REST） | **이용허락범위 제한 없음**（可商用/可演绎） | ❌ 需 key（401） | **7/7**（成分+含量在操作 3） | 条数需 key 后现查 | **推荐·首选**（字段最全）；**卡点=账号** |
| **B** | **data.go.kr `15067462` + `15067461`** HIRA 약가마스터（CSV） | **공공누리 제1유형**（출처표시） | ✅ **匿名可下**（实测 200） | 6.5/7（**成分 52%**） | **309,889 行 / 97,356 品目 / 109,231 商品名** | **推荐·立即可做**（v1.2.0 不必空等） |
| C | `data.mfds.go.kr`「의약품 제품 허가정보」파일데이터（MFDS 自家 CSV） | 同 MFDS「이용허락 제한 없음」 | ❌ 需登录（K3 实测：匿名直链被导 `/error/error`） | 7/7（官方字段说明同 A） | 未取（账号墙） | **备用·人肉通道**：韩国朋友下载后交文件即可（许可允许） |
| D | `nedrug.mfds.go.kr` 의약품안전나라 | 无 공공누리 标识；`robots.txt` = **`Disallow: /`** | ❌（页面可人工查，禁自动化） | 6.5/7（详情页） | 只能逐条人工 | **不采用**（仅作 K2 链接层，已上线） |
| E | `opendata.hira.or.kr` HIRA 自家开放数据 | **条款明确禁止**复制/加工/翻译/再发布/未授权自动化抓取 | ❌（产品级入口本机 400/503） | 汇总口径，非产品级 | — | **不采用**；但**同一机构的数据在 data.go.kr 上是 제1유형** → 走门户副本，不走 HIRA 站点（§3.2） |
| F | 국민건강보험공단（NHIS） | — | — | 无产品级药品目录（只有保险/就诊类统计） | — | **不采用**（无产品级数据） |
| G | `data.go.kr 15057639` 의약품 낱알식별（REST，**许可同上=限制 없음**，개발/운영均自动승인） | 이용허락범위 제한 없음 | ❌ 需 key | 只有 품목명/업체명/모양/색/식별표시，**无成分无含量** | — | **不采用**（补不了核心字段；但若将来做「药片外观识别」可回看） |
| H | `data.go.kr 15127983` HIRA DUR 목록 / `15020627` MFDS 统计表 | 제1유형 | ✅ 文件免登录 | DUR = 禁忌清单（非注册库）；统计表 = 63 行汇总 | — | **不采用**（不是产品注册清单） |

**推荐组合**：
1. **立刻**按 **B** 起 v1.2.0（零阻塞，KOGL 제1유형，商品名/规格/MAH/注册号/状态/ATC 齐；成分 52% 覆盖，其余丢弃计数并在覆盖页写明口径）。
2. **并行**等人给 **A** 的 key（或 C 的 CSV）→ 拿到后**同一条 ETL 再跑一遍 A**，把 B 缺的成分补齐（`품목기준코드` ↔ `ITEM_SEQ` 可直接 join，无需模糊匹配）。**B 不是白做，是 A 的骨架与校验基线。**

## 6 路线、卡点、需要人做什么（一句话版）

- **KR 走哪条路**：B 先上（HIRA 文件，免账号、许可够），A 随后补（MFDS API，字段全）——两者用 `품목기준코드`/`ITEM_SEQ` 对齐。
- **卡点是什么**：**只有 A 的账号**——`data.go.kr` 注册的「본인인증」必须韩国自然人；**企业会员也绕不过**（6 步里的第 4 步）。
- **需要人做什么**：①（推荐）请一位韩国籍熟人用本人实名登录 → 对 `15095677` 点「활용신청」（개발단계 자동승인，10,000 次/日）→ 把 `Encoding 인증키` 给 Lead（只进 `.env`）；或直接给「의약품 제품 허가정보」CSV。②（不阻塞）批准先用 B 起 v1.2.0。

## 7 入库成本与风险（写库窗口由 backend 执行，本轮不实施）

| 项 | Route B（HIRA 文件） | Route A（MFDS API） |
|---|---|---|
| 人时 | **4–6 人时** | **6–9 人时**（含 key 申请后的联调） |
| 数据体量 | 2 个 CSV（59.6 MB）→ 品目 97,356 / 行 309,889 / 商品名 109,231 | 3 操作分页；条数等 key 后 `totalCount` 现查 |
| 必需 ETL 动作 | CP949 解码；`표준코드`↔`주성분` 按 `일반명코드` join；`약품규격` 正则（4,256 值，数字+韩文单位）；**丢弃无成分码的 47,761 行/品目并计数**；`취소일자` 语义待确认前只存不判定 | 3 操作按 `ITEM_SEQ` join；**剔除 `*_DOC_DATA` 说明书正文**；`QNT`+`INGD_UNIT_CD` 原样存 |
| 主要风险 | ① 成分覆盖 52%（西药 63.7%）→ 覆盖页必须写明；② 급여口径 ≠ 全部上市；③ `취소일자`≠허가취소（待确认）；④ 韩文商品名，无英文名 | ① key 取决于人；② `운영계정` 需 심의；③ 说明书文本字段不得入库；④ 韩/英双语名需决定展示哪语 |
| 不做 | 不转载说明书正文、不存价格、不做剂量换算、不做替代推荐、不抓 nedrug（robots 全站禁） | 同左 |

## 8 书面申请（已起草，**未发送**）

`docs/许可请求-韩国KR-韩英双语.md`：韩语 + 英语两版，收件人为 **식품의약품안전처 데이터혁신기획팀**（043-719-1627，见数据集页）与 **공공데이터포털 문의**，问三件事：
(a) 「이용허락범위 제한 없음」是否覆盖**海外网站**对事实字段的再发布；(b) **非韩国法人/个人无韩国手机号**能否获得 `활용신청` 或文件（若不能，请指明替代通道）；(c) 推荐署名句式与数据基准日写法。
承诺：只存事实字段、署名 + 许可链接 + 基准日、不转载说明书正文、不商用销售、不暗示背书、可随时撤销授权。
**发送需 SMC 邮箱登录态（LG14），归 Lead，本轮只交草稿。**

## 9 证据清单（全部官方 URL；抓取日 2026-11-22 北京时间）

| # | URL | 用途 |
|---|---|---|
| 1 | <https://www.data.go.kr/data/15095677/openapi.do> | 数据集页（许可/费用/频率/심의/流量/字段规范） |
| 2 | <https://www.data.go.kr/en/data/15095677/openapi.do> | 英文页（`Scope of License = The use permission range limitless`） |
| 3 | <https://www.data.go.kr/biz/dcat/metadata/15095677.do> | DCAT（`dct:rights` 同文本） |
| 4 | <https://www.data.go.kr/catalog/15095677/openapi.json> | schema.org（license + isAccessibleForFree） |
| 5 | <https://www.data.go.kr/ugs/selectPortalPolicyView.do> | 门户政策（별도 신청절차 없이 이용 / 제3자 권리 / 공공누리 유형표 / 이용약관） |
| 6 | <https://auth.data.go.kr/sso/common-signup> | 注册会员类型与步骤（内国人/国税厅事业者/본인인증） |
| 7 | <https://auth.data.go.kr/sso/corp-certify> | 기업회원 认证入口 |
| 8 | <https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService08/getDrugPrdtPrmsnInq08>（无 key） | 账号墙实测（401） |
| 9 | <https://www.data.go.kr/data/15067462/fileData.do> | HIRA 표준코드（제1유형 / 免登录下载原文） |
| 10 | <https://www.data.go.kr/data/15067461/fileData.do> | HIRA 주성분（제1유형） |
| 11 | <https://www.data.go.kr/biz/dcat/metadata/15067462.do> · `…/15067461.do` | DCAT `dct:rights` = 제1유형 |
| 12 | <https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000007666876&fileDetailSn=1> | 匿名下载实测（200，55,741,167 B） |
| 13 | <https://nedrug.mfds.go.kr/robots.txt> | `Disallow: /`（不采用，仅链接层） |
| 14 | <https://opendata.hira.or.kr/op/opb/selectUseAgrmtInfoView.do> | HIRA 自家条款（禁止再发布，见 `reports/2026-11-19-kr-account-free-sources.md`） |
| 15 | <https://www.kogl.or.kr/info/license.do> | 공공누리 官方类型页（**本机不可达**，用 #5 门户副本代替，未绕） |

## 10 复现命令（只读；不写库）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$ev = 'data\raw\kr\evidence-20261122'
# 1) 数据集页 / DCAT / 政策 / 注册
Invoke-WebRequest -UseBasicParsing 'https://www.data.go.kr/data/15095677/openapi.do'   -OutFile "$ev\data-go-kr-15095677-ko.html"
Invoke-WebRequest -UseBasicParsing 'https://www.data.go.kr/ugs/selectPortalPolicyView.do' -OutFile "$ev\data-go-kr-portal-policy.html"
Invoke-WebRequest -UseBasicParsing 'https://auth.data.go.kr/sso/common-signup'         -OutFile "$ev\auth-data-go-kr-signup.html"
# 2) 账号墙：无 key → 401
Invoke-WebRequest -UseBasicParsing 'https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService08/getDrugPrdtPrmsnInq08?pageNo=1&numOfRows=3&type=json'
# 3) 文件数据（官方明示免登录）
Invoke-WebRequest -UseBasicParsing 'https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000007666876&fileDetailSn=1' -OutFile 'data\raw\kr\20261122\hira_yakga_stdcode_20260831.csv'
Invoke-WebRequest -UseBasicParsing 'https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_000000007759104&fileDetailSn=1' -OutFile 'data\raw\kr\20261122\hira_yakga_ingredient_20261105.csv'
# 4) 实测条数与覆盖（一次性分析脚本，不入库；在 data\raw\kr\evidence-20261122\scripts\）
& $py 'data\raw\kr\evidence-20261122\scripts\kr_hira_stats.py'
& $py 'data\raw\kr\evidence-20261122\scripts\kr_hira_item_cov.py'
& $py 'data\raw\kr\evidence-20261122\scripts\kr_spec_shape.py'
```

## 11 只读声明与遗留

- **未做**：注册 / 登录 / 提交表单 / 伪造身份或 UA / 绕 WAF / 发信 / 写 `data/drugs.db` / 跑 ingest / 建站 / commit / 发布。
- **已落盘**：`data/raw/kr/evidence-20261122/`（页面快照 + README）+ `data/raw/kr/20261122/`（2 份 KOGL 제1유형 CSV，59.6 MB）。两者都在 `data/raw/`（不入库），**不批 Route B 可直接删**。
- **未验证 / 待确认**：① `15095677` 实际条数与 `numOfRows` 上限（需 key）；② HIRA `취소일자` 是「급여 삭제」还是「허가 취소」；③ `운영계정` 심의승요 对非商业站是否必需；④ kogl.or.kr 本机不可达，공공누리 原文用门户副本。
- **口径提醒（写库时必须同步）**：覆盖页写「식약처/HIRA 공공데이터（급여 약가마스터 기준）」**不写**「韩国全部药品」；Route B 的成分缺失率 **48.0% 品目（50,595 有码 / 97,356 总数）** 必须在覆盖页与 `source` 备注里写清。

_本报告只做评估，不含任何写库、ingest、建站、测试或发布动作。_
