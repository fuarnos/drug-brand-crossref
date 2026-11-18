# 韩国英文版官方站点注册入口 / 外籍注册条件实测（K4，只读）

- 日期：2026-11-19（北京时间谷段）
- 工位：search-alias（task-12）
- 用户追加指令：「韩国那个网站英语版没给注册链接，你试试看英语版网站再找找看」
- **结论：② 英文站同样没有「不用韩国手机号/实名」的注册路径。**
  英文站（`data.go.kr/en/`）没有可用的注册入口（注册路径 404、登录页 500）；
  韩文注册页 `auth.data.go.kr/sso/common-signup` 的会员类型只有
  **일반회원（만 14세 이상 내국인）/ 어린이 회원（만 14세 미만 내국인）/ 기업회원（국세청 등록 사업자）**，
  页面里 **没有 외국인 / 여권 / FOREIGN 任何选项**；第 4 步固定是「본인인증」。
  英文站也**没有免登录直接下载**的产品级文件：数据集英文页的下载按钮明确要求登录。
- 本轮**只 GET、未注册、未登录、未提交表单、未伪造身份/UA、未绕 WAF**；
  证据快照 6 份在 `data/raw/kr/evidence-en/`。

## 1. 逐站实测

| # | 英文站 | 实测 | 语言/注册入口 | 结论 |
|---|---|---|---|---|
| 1 | `www.mfds.go.kr/eng/`（식약처英文站） | **200**（63 KB，最终 `/eng/index.do`） | 英文；导航是 News/Food/Drugs/Approval…，**未见 Open Data / Public Data / Join / Sign up 链接** | 只是英文信息站，没有注册/数据下载入口 |
| 2 | `data.mfds.go.kr`（식의약 데이터 포털） | 首页 **200**（222 KB） | `html lang="ko"`、页面变量 `isEngLang=false`；`/eng/`、`/en/` 均 **404** | **没有英文版**；注册/登录按韩文站，仍要韩国实名（K1/K3 结论） |
| 3 | `nedrug.mfds.go.kr`（의약품안전나라） | `/eng/`、`/en/` 均 **200 但为 soft-404**（2.8 KB，正文「요청하신 페이지를 찾을 수 없습니다」） | 首页 `lang="ko"`，无语言切换；`robots.txt` 仍是 `User-agent: * / Disallow: /`（K3 已实测） | **没有英文 UI**；产品详情只能韩文页面人工看 |
| 4 | `www.data.go.kr/eng/`、`/en/` | `/eng/` **404**；`/en/` **404**；实际英文首页是 **`/en/index.do` 200**（69 KB） | 英文站导航里**没有 Sign up / Join**；唯一相关链接是登录 `/en/uim/login/loginView.do`（本机 GET **500**） | 用户观察属实：英文站不给注册链接 |
| 5 | 数据集 15095677 英文页 | `https://www.data.go.kr/en/data/15095677/openapi.do` **200**（94 KB） | 「Scope of License」= **`The use permission range limitless`**（即「이용허락 제한 없음」）；下载按钮脚本：`Login is required. … /en/uim/login/loginView.do`、`Please log in to use this service.` | 许可允许再发布，但**必须先登录/申请**；无免登录下载 |

## 2. 注册入口与要求（原文）

### 2.1 英文站：没有注册入口

- `https://www.data.go.kr/en/index.do`（200）中**没有 Sign up / Join / Register** 链接；
- 可猜测的英文注册路径全部 404：
  `/en/uim/login/signupView.do`、`/en/uim/login/signupView.do?lang=en`、
  `/en/tcs/mem/join/joinStep1.do`、`/en/tcs/mem/join.do`、`/en/uim/member/joinView.do`；
- 英文登录页 `/en/uim/login/loginView.do` 本机 GET **500**（无法从英文站进入注册流程）；
- 数据集英文页的登录弹窗只指向 `/en/uim/login/loginView.do`，**没有「Sign up」旁边入口**。
- `www.mfds.go.kr/eng/` 也没有 Join/Sign up；`data.mfds.go.kr` 没有英文版。

### 2.2 韩文注册页（英文站没有，但它是实际唯一入口）

`https://www.data.go.kr/uim/login/signupView.do` → **302/跳转**到
`https://auth.data.go.kr/sso/common-signup`（**200**，21.5 KB，`html lang="ko"`）。原文：

> 회원가입
> 회원가입을 하시면 공공데이터포털을 통해 국가가 보유하고 있는 공공데이터와 오픈API 등
> 모든 정보를 자유롭게 이용하실 수 있습니다.
>
> 1단계 회원구분 → 2단계 약관동의 → 3단계 정보입력 → **4단계 본인인증** → 5단계 가입완료
>
> **일반회원** — 만 14세 이상 **내국인**
> **어린이 회원** — 만 14세 미만 **내국인**
> **기업회원** — 국세청에 등록된 사업자

会员类型代码只有 `COMMON` / `CHILD` / `CORP`；页面全文检索
`FOREIGN`、`foreign`、`외국인`、`여권`、`passport` 均为 **0 次**。
→ **没有外国人/护照注册选项**；且第 4 步「본인인증」是必经步骤（2026-11-18 已确认
`data.mfds.go.kr` 的本인인증由韩国信用信息局 + KG Mobilians 用**韩国手机号**做实名）。

### 2.3 直接回答三个问题

1. **英文站注册入口 URL**：**没有**。
   - 唯一可找到的英文登录入口：`https://www.data.go.kr/en/uim/login/loginView.do`（本机 500）；
   - 英文注册路径全部 404（见 2.1）；
   - 实际注册页是韩文 `https://www.data.go.kr/uim/login/signupView.do`
     → `https://auth.data.go.kr/sso/common-signup`。
   - 要求：会员类型限 **내국인（内国人人）/ 国税厅登记事业者**，第 4 步 **본인인증**；
     页面无 외국인/여권 选项；邮箱只用于「가입확인」，不是无手机注册通道。
2. **有没有不用韩国手机号的注册路径**：**没有证据支持**。英文站不给入口；韩文站会员类型
   写死「내국인」且无外国人选项；本인인증 是必经步骤（韩国手机实名，见 K3/2026-11-18 证据）。
   没有「邮箱直接注册」「护照注册」「외국인등록번호注册」的入口。
3. **英文站有没有免登录直接下载的文件**：**没有**。
   - 数据集英文页：`Scope of License = The use permission range limitless`，但下载/调用
     一律 `Login is required` → `/en/uim/login/loginView.do`；申请状态
     `Development level: allowed / Operation level: Not allowed`（生产要审批）；
   - `data.mfds.go.kr/file/downloadFile` 匿名请求仍被导到 `/error/error`（K3 已实测）；
   - `www.mfds.go.kr/eng/` 只有新闻/介绍，无产品级数据文件；
   - `nedrug` 没有英文 UI（`/eng/`、`/en/` soft-404），韩文页仍受 robots `Disallow: /` 限制。

## 3. 判断与建议

- **结论②**：英文站不是「免账号」的新口子；它只是韩文门户的英文介绍层，
  注册仍回到韩文 `auth.data.go.kr`，且只面向内国人/韩国企业。
- 与 K3 一致：**维持 K2 链接层**（覆盖页/About 链 `nedrug.mfds.go.kr` + 说明「需本人注册」）；
  不新增数据、不入库。
- 若用户愿意走人工：唯一路径仍是找有韩国手机号的人完成 `data.go.kr` / `data.mfds.go.kr`
  实名 → 申请 `15095677` API key 或下载 CSV → 交 agent 入库；或向 MFDS 书面申请再发布许可。
- 不要用第三方镜像/伪造身份/绕过验证。

## 4. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://www.mfds.go.kr/eng/'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://www.data.go.kr/en/index.do'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://www.data.go.kr/en/data/15095677/openapi.do'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://www.data.go.kr/en/uim/login/loginView.do'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://www.data.go.kr/uim/login/signupView.do'   # 跳 auth.data.go.kr/sso/common-signup
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://nedrug.mfds.go.kr/eng/'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://data.mfds.go.kr/eng/'
```

## 5. 证据文件

`data/raw/kr/evidence-en/`（只读页面快照；不含任何下载数据）：

| 文件 | 来源 | 大小 |
|---|---|---|
| `mfds-eng-home.html` | `www.mfds.go.kr/eng/`（200） | 63,121 B |
| `data-mfds-home-ko.html` | `data.mfds.go.kr/`（200，`lang=ko`、`isEngLang=false`） | 221,835 B |
| `nedrug-eng-soft404.html` | `nedrug.mfds.go.kr/eng/`（200 但 soft-404） | 2,833 B |
| `data-go-kr-15095677-en.html` | `/en/data/15095677/openapi.do`（200，许可+登录提示） | 94,500 B |
| `data-go-kr-signup-kr.html` | `auth.data.go.kr/sso/common-signup`（200，会员类型） | 21,522 B |
| `data-go-kr-en-index.html` | `www.data.go.kr/en/index.do`（200，无注册入口） | 69,295 B |

另记录（未存正文）：`/en/uim/login/signupView.do` 404；`/en/uim/login/loginView.do` 500；
`data.mfds.go.kr/eng/`、`/en/` 404；`www.data.go.kr/eng/` 404。
未写库、未改 etl、未注册/登录/提交表单、未伪造身份或 UA、未绕 WAF。
