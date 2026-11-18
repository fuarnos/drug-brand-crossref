# 韩国「免账号」产品级数据源调研（K3，只读实测）

- 日期：2026-11-19（北京时间谷段）
- 工位：search-alias（task-11）
- 用户指令：「韩国先开始找不需要账号的数据吧」
- **结论：② 未找到「免账号 + 许可允许再发布 + 可批量」的韩国产品级数据源。**
  官方产品级数据仍在账号墙后；nedrug 公开页可人工查、字段较全，但 `robots.txt` 全站
  `Disallow: /` 且无公开批量许可；HIRA 公开的是**汇总统计**，条款明确禁止复制/加工/
  再发布/未授权抓取。建议维持 K2「只做官方查询链接、不入库」，直到有韩国账号或 MFDS
  书面许可。
- 本轮**未注册、未登录、未伪造 UA、未绕 WAF、未写库、未改 etl**；只保存了 6 份页面
  证据到 `data/raw/kr/evidence/`（不含批量数据、不含 20 条样本——结论②不需要样本）。

## 1. 逐源结论

| # | 源 | 本机实测（HTTP） | 许可 / 条款 | 字段覆盖（7 项） | 更新频率 | 批量性 | 判定 |
|---|---|---|---|---|---|---|---|
| 1 | **의약품안전나라 nedrug.mfds.go.kr** 公开检索/详情 | `/index` **200**（3.77 MB）；`/searchDrug?searchYn=true&itemName=타이레놀` **200**（447 KB，`총 7 건`）；详情 `getItemDetail?itemSeq=202201300` **200**（216 KB） | `robots.txt` = **`User-agent: * / Disallow: /`**（全站禁抓）；无 공공누리 标识；MFDS 版权政策：依《저작권법》第24-2条公开著作可自由利用+须注明出处，但**未附공공누리 的资料须先与主管部门协商** | **6.5/7**：品名✅、成分✅（원료약품 및 분량：성분명/분량/단위/규격）、规格✅、剂型✅（DUR 제형）、MAH✅（업체명）、许可日✅（허가일）、许可号△（详情只有품목기준코드；检索列表有허가번호）；状态△（列表有취소/취하列） | 实时（页面缓存带 updateTs，如 2026-10-22） | **只能逐条页面**；检索页有「엑셀 다운로드」但走 POST `/searchDrug/getExcel`，上限 10,000 行，且 robots 全站禁抓 | **不可作批量源**（可人工查询；批量=违反 robots/需先协商） |
| 2 | **식의약 데이터 포털 data.mfds.go.kr**「파일데이터 → 연도별 공공데이터 파일」 | 首页 **200**（222 KB）；`/cntnts/20` 使用说明 **200**（42 KB）；直链 `/file/downloadFile?fileSeq=…` **200 但最终落到 `/error/error`**（5.9 KB 错误页） | 使用说明原文：「포털 로그인 ⇒ … ⇒ 다운로드 및 이용」（登录后才能下载）；2026-11-18 已确认注册要**韩国手机实名** | 同 MFDS 许可信息（品目/成分/包装/허가 等，登录后才有） | 年度/不定期 | 文件批量（登录后） | **账号墙**（同 K1 结论，无变化） |
| 3 | **HIRA 건강보험심사평가원** 약제급여목록/약가 | `opendata.hira.or.kr` 首页 **200**（229 KB）；공공데이터 목록 **200**（236 KB）；「약제 급여 목록 현황」**200**（234 KB，**只有 등재품목수 汇总**，附 Excel 下载）；`약제급여목록표` 公告板 `bbsDummy.do?pgmid=HIRAA030014050000` 多次实测 **400**（个别 **503**） | **이용약관 200（249 KB）明确禁止**：超出个人使用的复制/加工/翻译/二次利用/发布；商业使用；未经事前同意的抓取/爬虫/宏等自动化提取 | 汇总统计：등재품목수/연도별（非产品级）；产品级列表**本机未取到** | 汇总按年度；公告板不定期 | 汇总 Excel 可下；产品级列表未验证 | **许可不允许再发布**；产品级入口本机 400/503，不能作为源 |
| 4 | MFDS 其他公开资料（보도자료/공시/许可统计） | `www.mfds.go.kr` **200**（163 KB） | 版权政策同上（公开著作可自由利用+出处，非공공누리需协商） | 新闻/统计，非产品级目录 | 不定期 | 非结构化 | 排除（无产品级） |
| 5 | **KIDS 한국의약품안전관리원** | `www.kids.or.kr`、`kids.or.kr`、`www.kidskorea.or.kr` 均 **DNS 无法解析**（本机） | 未能取页，无法核对 | — | — | — | **本机不可达**（不代表线上不存在；需换网络复核） |
| 6 | 국가법령정보 / 地方法规 | — | — | 只有法规条文，无产品级 | — | — | 排除（任务已注明） |

> 2026-11-18 已否掉、本轮未重复的路径：`data.go.kr` 会员（韩国手机实名）、
> `data.mfds.go.kr` 文件版（同样手机真名验证）、nedrug 文件下载（已停）。

## 2. 关键证据

### 2.1 nedrug 公开可读，但 robots 全站禁抓

```
GET https://nedrug.mfds.go.kr/robots.txt   → 200
User-agent: *
Disallow: /
```

- `https://nedrug.mfds.go.kr/index` → 200；`/searchDrug?searchYn=true&itemName=타이레놀`
  → 200，页面 `총 7 건`，7 个 `itemSeq` 可打开详情。
- 详情页字段（样例 `itemSeq=202201300`「타이레놀산500밀리그램(아세트아미노펜)」）：
  제품명 = 타이레놀산500밀리그램(아세트아미노펜)；업체명 = 켄뷰코리아판매유한회사；
  허가일 = 2022-04-04；품목기준코드 = 202201300；전문/일반 = 일반의약품；
  원료약품 및 분량 / DUR 제형 区块可读。
- 检索页有 `downExcelFile()` → `$.download('/searchDrug/getExcel', 'searchDetail', 'post')`，
  上限 10,000 行；**但这是页面功能，不是公开 API/许可**；robots 全站 `Disallow: /`
  意味着不应做自动化批量抓取。
- 页面未见 공공누리 标识；MFDS 版权政策写明「未附공공누리 的资料使用前须与主管部门协商」。

### 2.2 data.mfds.go.kr 直链匿名下载被拒

```
GET https://data.mfds.go.kr/file/downloadFile?fileSeq=1&servFileName=test.csv&ecmType=I
→ 200，最终 URL = https://data.mfds.go.kr/error/error （5,881 B HTML 错误页）
```

- 首页/使用说明公开可读，但原文写明「포털 로그인 ⇒ … ⇒ 다운로드 및 이용」。
- 页面里的「연도별 공공데이터 파일」列表由 JS 渲染，下载按钮调用
  `gfnFileDownload(fileId, servFileName)` → `/file/downloadFile`；匿名请求被导到错误页。

### 2.3 HIRA 条款明确禁止再发布/抓取

`https://opendata.hira.or.kr/op/opb/selectUseAgrmtInfoView.do`（200，249 KB）原文摘录：

> 서비스를 이용하여 얻은 정보를 이용자의 개인적인 이용 외에 복사, 가공, 번역, 2차적
> 저작 등을 통하여 복제, 공연, 방송, 전시, 배포, 출판 등에 사용하거나 제3자에게
> 제공하는 행위（禁止）
>
> 심사평가원의 사전승낙 없이 기술적 수단(스크래핑, 캡처, 크롤러, 로봇(봇), 매크로 등
> 데이터 추출 프로그램 및 기타 자동화 수단)을 사용하여 … 정보를 수집（禁止）
>
> 이용자는 서비스를 이용하여 얻은 정보를 가공, 판매하는 행위 등 … 상업적으로 사용할 수
> 없다（禁止）

- `약제급여목록표` 公告板入口 `bbsDummy.do?pgmid=HIRAA030014050000` 在本机多次实测
  **400**（一次 503），未取到产品级 Excel；`opendata.hira.or.kr` 的
  「약제 급여 목록 현황」只有 `등재품목수` 汇总（单位：품목），不是产品清单。
- 注：HIRA 的「완제의약품 유통정보통계」「급여의약품·치료재료청구현황」也是统计口径，
  不是注册库；且同受上述条款约束。

### 2.4 其他

- KIDS 三个域名本机 DNS 无法解析（`www.kids.or.kr` / `kids.or.kr` / `www.kidskorea.or.kr`），
  未能核对；不作为可用源。
- `www.mfds.go.kr` 只有 보도자료/공시/统计，无产品级目录；版权政策同上。

## 3. 字段覆盖（对照本站需要的 7 项）

| 源 | 品名 | 成分 | 规格 | 剂型 | MAH | 许可号 | 许可日期 | 状态 |
|---|---|---|---|---|---|---|---|---|
| nedrug 公开详情页 | ✅ | ✅ | ✅ | ✅ | ✅ | △（详情只有품목기준코드；列表有허가번호） | ✅ | △（列表有취소/취하列） |
| data.mfds 文件版（登录后） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅（按数据集字段） |
| HIRA 汇总 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗（只有等载品目数） |

## 4. 判断与建议

1. **结论②**：在「不注册、不提供韩国手机号/实名」前提下，**没有**同时满足
   「免账号 + 许可允许事实字段再发布 + 可批量」的韩国产品级源。
   - nedrug 是唯一「免登录可读、字段接近 7/7」的产品级页面，但 **robots 全站禁抓**、
     无批量 API、无 공공누리 标识（非공공누리 需先协商）→ **不能用来批量取数/再发布**，
     只能作为人工查询入口（与 K2 链接层一致）。
   - data.mfds 文件版匿名直链被导错误页；注册要韩国手机实名（K1 结论不变）。
   - HIRA 条款明确禁止再发布/抓取；公开的只是汇总统计。
2. **不要做**：不用 Kaggle/HF/第三方镜像（许可不可追溯）；不伪造 UA/不绕 WAF；
   不把 nedrug 页面批量爬下来入库。
3. **下一步（等人）**：
   - 让有韩国手机号的人完成 `data.go.kr` / `data.mfds.go.kr` 实名 → 拿
     `15095677` API key 或「연도별 공공데이터 파일」CSV → 跑 `etl/markets/kr.py`；
   - 或向 MFDS 书面申请「공공데이터 제공/이용 협의」拿到再发布许可后，再做批量；
   - K2 链接层保持不变（覆盖页/About 已上线）。
4. **若只想先做「医保目录层」**：HIRA 条款不允许再发布，不能做；除非获得 HIRA 事前同意。

## 5. 复现命令

```powershell
# 只读、匿名、不伪造 UA
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://nedrug.mfds.go.kr/robots.txt'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://nedrug.mfds.go.kr/searchDrug?searchYn=true&itemName=%ED%83%80%EC%9D%B4%EB%A0%88%EB%86%80'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail?itemSeq=202201300'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://data.mfds.go.kr/cntnts/20'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://data.mfds.go.kr/file/downloadFile?fileSeq=1&servFileName=test.csv&ecmType=I'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://opendata.hira.or.kr/op/opb/selectUseAgrmtInfoView.do'
Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 'https://www.mfds.go.kr/wpge/m_34/de010803l001.do'
```

## 6. 证据文件

`data/raw/kr/evidence/`（只读页面快照；不含批量数据）：

| 文件 | 来源 | 大小 |
|---|---|---|
| `nedrug-robots.txt` | `nedrug.mfds.go.kr/robots.txt` | 29 B |
| `nedrug-search-acetaminophen.html` | `/searchDrug?searchYn=true&itemName=타이레놀` | 447,747 B（7 条结果） |
| `nedrug-detail-202201300.html` | `/pbp/CCBBB01/getItemDetail?itemSeq=202201300` | 216,222 B |
| `data-mfds-anonymous-download-error.html` | `/file/downloadFile` 匿名请求最终错误页 | 5,884 B |
| `mfds-copyright-policy.html` | MFDS 저작권정책 | 128,361 B |
| `hira-opendata-terms.html` | HIRA 공공데이터 이용약관 | 248,980 B |

> 未落 20 条样本：结论是②（没有可合法批量再发布的源），样本会误导成「可用数据」。
> 本轮未写 `data/drugs.db`、未改 `etl/`、未注册/登录、未绕 WAF、未发布。
