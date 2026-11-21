# 韩国 KR 书面许可 / 咨询信（韩语 + 英语，草稿，**未发送**）

> 用途：对 `data.go.kr` 数据集 **15095677**（식품의약품안전처「의약품 제품 허가정보」）的**再发布确认 + 非韩国主体获取通道**做书面咨询。
> 依据：`reports/2026-11-22-kr-license-assessment.md`（§0 需人、§2 许可证据、§8 申请）。
> **纪律**：本文件只是草稿。**发送需 SMC 邮箱登录态（LG14），由 Lead 执行**；发出后必须在 `docs/跟进提醒.md` 记节点，不重复发。
> 与 `docs/许可请求-韩国MFDS-韩文说明.md` 的区别：那份是**给韩国朋友看的求助说明**（请对方代下 CSV/代申请 key）；**本文件是发给机构的正规书面咨询**（问许可范围与海内外主体通道）。

---

## 0 发送前的三个事实（写给发信人）

1. 数据集许可页原文已经是「**이용허락범위 제한 없음**」（英文 `The use permission range limitless`）、`무료`、`실시간`——**许可本身不需要再"申请"**；这封信问的是**两件含糊处**：
   (a) 该许可是否**同样覆盖海外（非韩国）站点**对**事实字段**的再发布；
   (b) **没有韩国手机号/实名**的外国个人或法人，**有没有合法获取通道**（若没有，请书面说明，我们就不做，只保留官方查询链接）。
2. 收件对象（数据集页明示）：**식품의약품안전처 데이터혁신기획팀**，管理부서 전화 **043-719-1627**；数据集页自带「오류신고 및 문의」弹窗（发送需门户登录）。
   **具体邮箱地址需发送时从官网「문의 / 국민소통」页现查**——本轮不猜、不写死（避免发错地址）。
3. 备用通道：`data.mfds.go.kr`（식의약 데이터 포털）同数据集的文件版；以及 `공공데이터포털` 自身的 문의 通道。

---

## 1 韩语版（正式邮件）

```text
제목: 「의약품 제품 허가정보」(데이터셋 15095677) 재배포 범위 및 해외 이용자 이용 문의

안녕하세요, 식품의약품안전처 데이터혁신기획팀 담당자님.

저희는 여러 나라의 의약품을 이름으로 대조해 주는 비영리 공개 참고 사이트
(https://drugcrossref.com/)를 운영하고 있습니다. 브랜드명·일반명·포장에 적힌
문구를 입력하면 해당 제품의 성분과 함량, 다른 나라의 대응 제품을 보여 주는
'신원 대조' 서비스이며, 복약 지도나 용량 계산, 대체 가능성 판단은 하지 않습니다.

공공데이터포털의 아래 데이터셋을 활용하고자 합니다.
  - 데이터셋: 식품의약품안전처_의약품 제품 허가정보 (데이터셋 번호 15095677)
    https://www.data.go.kr/data/15095677/openapi.do
  - 표기된 이용허락범위: 「이용허락범위 제한 없음」, 비용: 무료, 갱신: 실시간

저희가 저장하고자 하는 항목은 사실 정보에 한정됩니다.
  품목명(한글/영문), 주성분명과 분량·단위, 제형, 포장단위, 업체명,
  품목기준코드·품목허가번호, 허가일자, 취하 구분·일자, ATC 코드.
설명서 본문(효능효과·용법용량·주의사항 문서 데이터)은 저장하지 않으며,
원본 파일이나 전체 데이터를 그대로 재배포하지도 않습니다.

세 가지를 확인해 주시면 감사하겠습니다.
  (1) 「이용허락범위 제한 없음」이 대한민국 국외에 소재한 비영리 웹사이트에서
      위 사실 항목을 정규화하여 게시(재배포)하는 것까지 포함하는지.
  (2) 대한민국 휴대전화 본인인증이 없는 해외 개인·법인이 합법적으로 이 데이터를
      이용할 수 있는 절차가 있는지 (예: 기관 문의를 통한 파일 제공, 별도 신청 양식).
      현재 공공데이터포털 회원가입은 내국인 및 국세청 등록 사업자만 선택할 수 있고,
      4단계 본인인증이 필수여서 해외 이용자는 가입이 불가능한 상태입니다.
  (3) 권장 출처 표기 문구와 기준일 표기 방식.

저희는 다음과 같이 운용하겠습니다.
  - 출처 표기: 식품의약품안전처, 「의약품 제품 허가정보」, 공공데이터포털, 기준일 명시
  - 정규화(성분명 정리·단위 표준화)를 했음을 사이트에 명시
  - 상업적 판매, 광고, 유료 API 제공 없음 (현재 비영리·무광고)
  - 기관의 보증이나 승인을 암시하는 표현 사용하지 않음
  - 귀 기관의 요청이 있으면 즉시 게시 중단 및 데이터 삭제

바쁘신 중에 죄송합니다. 회신 주시면 그에 따라 진행하겠습니다.
감사합니다.

<보내는 사람 이름 / 소속>
<이메일>
```

---

## 2 英语版（同一封信，供英文渠道 / 国际邮箱）

```text
Subject: Request for clarification — re-use of "Pharmaceutical Product Authorization
         Information" (dataset 15095677) by a non-Korean non-commercial website

Dear Ministry of Food and Drug Safety (Data Innovation Planning Team),

We run a non-commercial public reference site (https://drugcrossref.com/) that helps
users identify a medicine by its brand name across countries. It maps a name to the
product's active ingredient and strength and to the corresponding products in other
countries. It gives no dosing advice, performs no dose conversion, and makes no
substitution recommendations.

We would like to use the following open dataset:
  - Dataset: Ministry of Food and Drug Safety_Pharmaceutical Product Authorization
    Information (dataset ID 15095677)
    https://www.data.go.kr/en/data/15095677/openapi.do
  - Scope of License shown on the dataset page: "The use permission range limitless"
  - Payment: Free / Update cycle: Real-time

We would store factual fields only:
  product name (Korean/English), active ingredient name with amount and unit,
  dosage form, pack unit, marketing authorisation holder, item code and
  authorisation number, authorisation date, cancellation type and date, ATC code.
We would NOT store the leaflet document data (efficacy, dosage, warnings), and we
would NOT redistribute the original files or the dataset as a whole.

We would be grateful for confirmation on three points:
  (1) Does "the use permission range limitless" also cover publication
      (re-distribution) of these factual fields, in normalised form, by a
      non-commercial website located outside the Republic of Korea?
  (2) Is there a lawful access route for a foreign individual or organisation that
      has no Korean mobile-phone identity verification? At present the portal's
      sign-up only offers "domestic resident" and "business registered with the
      National Tax Service", and step 4 identity verification is mandatory, so
      non-residents cannot register.
  (3) The attribution wording and the reference-date format you would prefer.

Our commitments:
  - Attribution: "Source: Ministry of Food and Drug Safety, Pharmaceutical Product
    Authorization Information, Public Data Portal (data.go.kr), as of <date>"
  - We will state on the site that we normalised the data (ingredient names,
    units) and that we are not the original publisher.
  - No commercial sale, no advertising, no paid API (currently non-commercial, ad-free).
  - No implication of endorsement by the Ministry.
  - We will remove the data immediately upon request.

Thank you for your time; we will follow whatever procedure you indicate.

Best regards,
<name / organisation>
<email>
```

---

## 3 发送清单（Lead 执行时逐条打勾）

- [ ] 从官网现查收件邮箱（식약처 데이터혁신기획팀 / 국민소통 문의），**不猜地址**
- [ ] 用 **SMC 邮箱**发送（登录态由人提供；凭据不进仓库）
- [ ] 主题行原样使用（便于对方检索）
- [ ] 附上数据集 URL（韩文页 + 英文页各一条）
- [ ] 发出后：`docs/跟进提醒.md` 记「已发送（无退信；未确认受理）」+ 首查 +1 周 / 复审 +1 月
- [ ] 回信到达：更新 `docs/许可清单.md` KR 行与 `docs/数据源调研清单.md` §6，再决定是否升级 Route A

## 4 不要写进信里的东西

- 不写「我们已经下载了你们的 CSV」（文件数据是公开免登录的，但没必要在信里提，避免引发误解）。
- 不写具体调用量估算、不写「请求配额提高」——本轮只问许可范围与通道。
- 不提第三方镜像 / 爬虫 / 代理，不提任何绕过手段。
- 不承诺任何无法兑现的事（例如「永不商业化」→ 现站口径是「当前非商业、无广告」，措辞保持可核验）。
