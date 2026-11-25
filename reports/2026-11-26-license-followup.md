# 许可跟进台账 2026-11-26：上海医保局到期 / NL CBG-MEB 首查后复核 / KR MFDS 状态

日期：2026-11-26（北京，UTC+8）｜执行：data-scout（task-3）｜台账：`docs/跟进提醒.md`
边界：**只读 web 抓取 + 只改 `docs/跟进提醒.md` 与本报告**；未写库、未 build、未发布、未 commit、未绕 WAF、未登录、未付费。
队列（`docs/谷段需求队列.md`）**本报告不改**，只给 Lead 一句建议（见 §5）。

## 0. 结论先行

| # | 事项 | 结论（2026-11-26） | 是否阻塞本站 |
|---|---|---|---|
| 1 | 上海市医保局 政府信息公开 `SQMB2F30661120261029001` | **今天 = 20 个工作日法定答复期，已到期；但「到期未确认」**——agent 无申请邮箱访问权限、仓库也未留存任何查询码/回执凭据（`查询码|查询密码|受理回执|回执号` 全仓除本报告 **0 命中**），因此**既不能确认已答复，也不能确认未答复** → 不记「逾期未复」、不标完成，**转人工核对** | 不阻塞任何已上线功能（该源本就未接入） |
| 2 | 荷兰 CBG-MEB · GIP 再发布许可（数据集 `87bf9724-971f-5bfc-82de-f2aef049bbd4`） | **有结论：无变化**。`dct:license` 仍为 `http://standaarden.overheid.nl/owms/terms/licentieonbekend`（许可未知）；11-25 首查节点已过，**未见任何答复/许可变更记录** | NL **继续不入库、不开 `nl` 语言**；下一节点 **2026-12-09** 复审 |
| 3 | 韩国 MFDS · `data.go.kr` `15095677` 书面咨询 | **仍未发送**：草稿 `docs/许可请求-韩国KR-韩英双语.md` 首行仍标「草稿，**未发送**」、发送清单第 1 项（SMC 邮箱）未打勾 → 卡在「人提供 SMC 邮箱登录方式」 | 不阻塞 KR Route B（HIRA 文件数据已可免账号入库） |

一句话：**今天没有新增许可**；上海到期但看不到结果（需人开邮箱看一眼），荷兰确认没变，韩国还差人给邮箱登录方式。

## 1. 复核明细（可复核）

### 1.1 荷兰 CBG-MEB GIP：`dct:license` 是否变了 → **没变**

抓取时间：2026-11-26 04:10 北京时间（UTC 2026-11-25 20:10）前后，`web_fetch` 单次 GET，无 cookie、无登录。

| # | URL | HTTP | 实测内容 | 判定 |
|---|---|---|---|---|
| A | `https://catalogus.datastelsel.nl/details?s=http%3a%2f%2fdata.overheid.nl%2fdataset%2f87bf9724-971f-5bfc-82de-f2aef049bbd4`（FDS **生产**目录） | 200 | 标题 `Geneesmiddeleninformatiebank`；`Licentie` = `http://standaarden.overheid.nl/owms/terms/licentieonbekend`；`dct:License` 同值；`accessRights` = `.../access-right/PUBLIC`；`rightsHolder` = `College ter Beoordeling van Geneesmiddelen`；法定依据 `Artikel 53 Geneesmiddelenwet`；联系点 `Geneesmiddelgebruik@cbg-meb.nl`；页首「Laatst bijgewerkt: 7 uur geleden」 | **许可未知（未变）** |
| B | `https://catalogus.simulatie.datastelsel.nl/details?s=...`（同一 UUID，FDS **模拟**目录） | 200 | 字段与 A 逐项一致，`dct:license` 同为 `licentieonbekend`（仅内部 `vb…` 节点 id 不同） | **旁证：未变** |
| C | `https://data.overheid.nl/dataset/87bf9724-971f-5bfc-82de-f2aef049bbd4` | **404** | 页面标题「Dataset niet gevonden」 | 与 11-11 一致：原入口仍不可达（因此沿用 FDS 目录镜像，同一条 DCAT 记录、同 UUID） |
| D | `https://data.overheid.nl/en/dataset/...` | **404** | 同上（英文侧「Dataset not found」） | 同上 |
| E | `https://data.overheid.nl/data/dataset/...` | **404** | 「Pagina niet gevonden」 | 同上 |
| F | `https://www.cbg-meb.nl/disclaimer` | **404** | 空 body | 与 11-11 一致：**仍无站内许可/条款页** |
| G | `https://www.geneesmiddeleninformatiebank.nl/` | — | **无法访问（抓取失败）**：https 被跨源 301 到 `http://www.geneesmiddeleninformatiebank.nl`，直取 http 报 `fetch failed` | **无法确认**（不影响主结论：许可字段以 DCAT 记录为准，本项只是「首页是否新增授权声明」的旁证） |

> 判定：**无变化**。`licentieonbekend` 在 `data.overheid.nl` 口径里 = 「geen hergebruik licentie / Open Data? Nee」（见 `reports/2026-11-11-nl-license-assessment.md` §1 第 3 行），因此 **NL 维持 🟡 待确认、不入库、不上线**。
> 「无变化」只说明目录元数据没改；**不能**据此推断 CBG-MEB 拒答——请求信 2026-11-11 发出、至今无回执落盘，属「未答复」而非「拒绝」。回复仍需人工在 `Geneesmiddelgebruik@cbg-meb.nl` 收件箱看。

### 1.2 上海市医保局：为什么只能写「到期未确认」

1. **到期日算得出来**（命令见 §4）：申请日 2026-10-29（周四），按「不含起始日、只数周一至周五」口径，
   10 个工作日 = **2026-11-12**（周四）、20 个工作日 = **2026-11-26**（周四，今天）、40 个工作日 = **2026-12-24**（周四）。
   20 个工作日与台账原记的 11-26 一致 ✔。
2. **法定依据**：《中华人民共和国政府信息公开条例》第三十三条——「不能当场答复的，应当自收到申请之日起 20 个工作日内予以答复；需要延长答复期限的，应当经政府信息公开工作机构负责人同意并**告知申请人**，延长的期限最长不得超过 20 个工作日」
   （实测引文：[北京市规划和自然资源委员会 · 依申请公开的答复时限](https://ghzrzyw.beijing.gov.cn/zhengminhudong/cjwt/202401/t20240131_3550910.html)，抓取 2026-11-26，HTTP 200）。
   → 由此可推：**若对方延期，必须先告知申请人**；所以「邮箱里有没有延期告知」本身就是可判定信号，**最晚可到 2026-12-24**。
3. **为什么不能自己查**：`ybj.sh.gov.cn` 首页实测可达（HTTP 200），但**答复走申请人自己的渠道**（申请邮箱/回执），
   而仓库里**只有申请编号的文字引用、没有任何查询码/回执凭据**（编号出现在台账/交接/报告里，但 `查询码|查询密码|受理回执|回执号` 除本报告外 **0 命中**，见 §4）。
   → 按纪律不猜、不试密码、不冒用身份，结论只能写 **「到期未确认（无邮箱/官网查询权限）」**。
4. **口径澄清**：**「到期未确认」≠「逾期未复」**。前者是「我看不到」，后者是「能确证超期未答复」；
   后者需要人工确认邮箱/官网结果后才能写。本条建议已写进台账（`docs/跟进提醒.md` 到期判定节）。

### 1.3 韩国 MFDS：状态没动

- `docs/许可请求-韩国KR-韩英双语.md` 首行：`# 韩国 KR 书面许可 / 咨询信（韩语 + 英语，草稿，**未发送**）`；
  §3 发送清单第 1 项 `- [ ] 用 **SMC 邮箱**发送（登录态由人提供；凭据不进仓库）` **未打勾** → **未发送**，与 11-22 台账一致。
- `docs/许可清单.md` §2.16 / 待办（第 255–256 行）仍把「KR 书面咨询信」列为「待 Lead 用 SMC 邮箱发出」。
- 不影响数据面：Route B（`data.go.kr` 上 HIRA 약가마스터两份，공공누리 제1유형、免登录）**已可入库**，咨询信只是 Route A（成分补齐）的前置。

## 2. 到期判定（按 `docs/跟进提醒.md` 顶部规则）

| 申请 | 节点 | 今天（2026-11-26）判定 | 当天动作 |
|---|---|---|---|
| 上海医保局 `SQMB2F30661120261029001` | **2026-11-26**（20 工作日） | **到期，结果不可见** → 标红一次 | 记「到期未确认」；台账补推算节点 **2026-12-24**（延期 20 工作日上限）；**不催办、不标完成** |
| 荷兰 CBG-MEB GIP | 2026-11-25（首查，**昨日已过**） | 已过节点 + 复核：**目录许可元数据无变化** | 台账状态追加「11-25 首查已过、11-26 复核无变化」；下一节点 12-09 复审 |
| 韩国 MFDS 咨询 | 待发（发出后 +7 天首查 / +30 天复审） | **未发送 → 无节点** | 台账只更新「仍未发送」，不设到期提醒 |
| 澳门 ISAF / 澳大利亚 TGA | 已闭环 | — | 不动 |

> 同一节点当天只提一次：本条即 2026-11-26 的唯一一次提醒（台账「开工核对记录」也只加一条）。

## 3. 需人做的事（3 条，按优先级）

1. **（今天/最迟本周）看申请邮箱**：查 2026-10-29 提交上海医保局那次用的邮箱（含垃圾箱/归档），找两样东西之一：
   ① **答复原件**（→ 转给 Lead，进队列评估数据可用性）；② **延期告知**（→ 说明最晚到 2026-12-24，台账改「已延期」）。
   都没有 → 请回一句「无答复」，我在下一次开工把它记成「逾期未复」并写后续（行政复议/重新申请另议，需人拍板）。
   *原因：agent 没有该邮箱访问权限，也没有查询码，这是唯一不能自动化的环节。*
2. **（不阻塞交付）KR 咨询信发送**：给 Lead 一次 **SMC 邮箱**登录方式（或人代发），发后我按 +7 / +30 天节点跟进。
3. **（低优先）NL**：如手上有 CBG-MEB 的回信（`Geneesmiddelgebruik@cbg-meb.nl`），转过来即可判定；否则 12-09 我再复审一次目录。

## 4. 复现命令 / URL

```powershell
# 1) 上海答复期换算（不含起始日、只数周一至周五）
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -c @"
from datetime import date, timedelta
def add_workdays(start, n):
    d, c = start, 0
    while c < n:
        d += timedelta(days=1)
        if d.weekday() < 5: c += 1
    return d
s = date(2026,10,29)
for n in (10, 20, 40):
    d = add_workdays(s, n); print(f'{n:>2} workdays after {s} = {d} {d:%A}')
"@
# 实测输出：10 → 2026-11-12 Thursday；20 → 2026-11-26 Thursday；40 → 2026-12-24 Thursday

# 2) 仓库里有没有查询码/回执凭据（实测：除本报告自身 0 命中）
Select-String -Path 'docs\*.md','reports\*.md' -Pattern '查询码|查询密码|受理回执|回执号' |
  Where-Object { $_.Path -notlike '*2026-11-26-license-followup*' }

# 2b) 编号本身只出现在文字台账里（台账 / 交接 / 报告引用，不附凭据）
Select-String -Path 'docs\*.md','reports\*.md' -Pattern 'SQMB2F30661120261029001' | Group-Object { Split-Path $_.Path -Leaf }

# 3) 北京日期（判定「今天」）
& $py -c "from datetime import datetime,timezone,timedelta; print(datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M %A'))"
# 实测输出：2026-11-26 04:09 Thursday
```

URL（全部为单次 GET、无登录、无 cookie）：

- FDS 生产目录（**主证据**）：<https://catalogus.datastelsel.nl/details?s=http%3a%2f%2fdata.overheid.nl%2fdataset%2f87bf9724-971f-5bfc-82de-f2aef049bbd4>
- FDS 模拟目录（旁证，同 UUID）：<https://catalogus.simulatie.datastelsel.nl/details?s=http%3a%2f%2fdata.overheid.nl%2fdataset%2f87bf9724-971f-5bfc-82de-f2aef049bbd4>
- `data.overheid.nl` 原条目（仍 404）：<https://data.overheid.nl/dataset/87bf9724-971f-5bfc-82de-f2aef049bbd4>
- `cbg-meb.nl/disclaimer`（仍 404）：<https://www.cbg-meb.nl/disclaimer>
- 条例第 33 条引文：<https://ghzrzyw.beijing.gov.cn/zhengminhudong/cjwt/202401/t20240131_3550910.html>
- 上海医保局首页（可达性旁证，HTTP 200）：<https://ybj.sh.gov.cn/>

## 5. 给 Lead 的一句队列建议（**未改队列文件**）

> 建议 `docs/谷段需求队列.md`「等待回复（申请台账）」里上海那一行，状态从「等待回复」改成 **「到期未确认（2026-11-26，待人工核对邮箱）」**，并把下一个提醒日期写成 **2026-12-24（延期上限）**；
> 同时把 KR 咨询信那条保持「待 Lead 用 SMC 邮箱发出」不动。**要不要改由 Lead 定**（本条只建议，不代改）。

## 6. 边界与已知缺口

- **没做的事**：未写库、未跑 ingest、未 build、未发布、未 commit；未访问任何需登录的页面；未尝试猜测查询码。
- **抓不到的**：GIP 首页（https→http 跨源跳转后直取失败）→ 已按「无法确认」记录，不影响 §1.1 结论。
- **口径没动的**：`docs/许可清单.md`（NL = 🟡、KR = 均未接入）本轮**无需改**——NL 仍是 `licentieonbekend`、KR 状态未变；
  若日后要改（例如 NL 拿到许可），按 §2.10 那条改并同步 `docs/欧盟抓取-20261111.md`。
- **下一节点**：上海 2026-12-24（推算上限，人工核对后可改）；NL **2026-12-09** 复审；KR 待发。
- **未登记的索引**：本报告**未写进** `reports/INDEX.md`（不在本工位写范围，由 Lead/收尾工位补一行）。
