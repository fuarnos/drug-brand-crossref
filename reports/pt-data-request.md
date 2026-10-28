# INFARMED 数据授权申请材料（CITS / INFOMED，pt-PT 主信 + EN/ZH）

> 日期：2026-10-28 ｜ 任务：`task-96` ｜ 依据：`reports/pt-audit.md`（task-92 审计）
> 性质：**用户本人发送**的申请材料（先问、不花钱）；本文件只写 `reports/` 与 `.tmp/pt-request/`，**未写 DB、未改 `site/build.py`、未 git/发布**。
> 公开版占位：`[NOME]` / `[E-MAIL]` / `[LOCALIDADE]` / `[DATA]`；**本地填充版**（真名/邮箱）在 `.tmp/pt-request/application-filled.md`（不入公开仓库、不发站点）。

---

## 0. 结论与建议动作

| 项 | 结论 |
|---|---|
| 申请渠道 | **CITS Portal da Cedência**（Portal CITS）注册 + 正式申请；邮件主渠道 **cimi@infarmed.pt**；电话 +351 21 798 7373 |
| 申请主体 | CITS 注册表单支持 **Pessoa Singular（个人）** / Pessoa Coletiva（机构）→ 个人开发者可以申请 |
| 费用 | 官方页面：**Administração Pública = Gratuito；Outras entidades = €150,00 (+IVA)/Ano**；访问期 **1 年**；先付款后开通；需签 **protocolo de cedência** |
| 公益/非商业豁免 | 官网**未公布**针对个人/非营利项目的豁免条款 → 信中明确询问「isenção/redução por interesse público」；**未获书面答复前不付款** |
| 数据形态（重要） | CITS 交付的是 **Access 文件（.mdb/.accdb），每日更新、固定结构**（《Manual da Cedência》v16.0，2026-01-16，64 页）；**不是** API；字段覆盖名称、DCI、dosagem、forma farmacêutica、embalagem、titular AIM、estado AIM/comercialização、**ATC**、CNPEM 等（比 INFOMED 网页公开字段更全） |
| 公开再发布 | 需在申请信中单独请求「reutilização pública não comercial」；承诺**署名 INFARMED、链回官网、不转售、不把原始文件作为独立数据集再分发**；是否允许须书面确认 |
| 禁止事项 | **不要抓取 INFOMED**：Guia 禁止未经书面许可复制/再发布，`robots.txt = Disallow: /`（task-92 已核实）；信中主动声明不 scraping，建立信任 |
| 退路 | 若未获授权：**不用 INFOMED 数据**；改用 EMA 集中审批开放数据（可再发布、须署名）做 EU 层，PT 市场保持 disabled；pt-PT UI 可先做（不依赖数据） |
| 发送清单 | ① 注册 CITS（Pessoa Singular）→ ② 发邮件到 cimi@infarmed.pt（葡文主信）→ ③ 等书面答复/协议 → ④ 明确费用与转载权后再决定付款 → ⑤ 收到 Access 文件后按 `reports/pt-audit.md` §2 映射写 ETL |

**下一步（人）**：把 `.tmp/pt-request/application-filled.md` 的葡文信复制进邮件，收件人 `cimi@infarmed.pt`，抄送可加 `infarmed@infarmed.pt`；主题用信中建议的「Assunto」。附件可附英文版/站点截图（可选），**不要先付款**。

---

## 1. 核实结果（2026-10-28，官网原文）

### 1.1 流程与表单

| 项 | 证据 |
|---|---|
| CITS 门户 | https://extranet.infarmed.pt/CITS-fo/ （HTTP 200）；页面「**Pedido de acesso ao Portal da Cedência — Formulário de pedido de acesso**」 |
| 主体类型 | 表单字段「**Tipo de Entidade\***：**Pessoa Singular / Pessoa Coletiva**」→ 个人可注册申请 |
| 申请入口 | https://extranet.infarmed.pt/CITS-fo/registo.jsf （HTTP 200） |
| 联系 | 页面/手册：**cimi@infarmed.pt**；电话 **+351 21 798 7373**；地址 Parque de Saúde de Lisboa, Av. do Brasil 53, 1749-004 Lisboa |
| 官方说明页 | https://www.infarmed.pt/web/infarmed/profissionais-de-saude/prescricao-e-dispensa/cedencia-de-base-de-dados-de-medicamentos 与 https://www.infarmed.pt/web/infarmed/cedencia-de-bases-de-dados-de-medicamentos （均 HTTP 200） |

### 1.2 费用与期限（官方原文）

> «Duração do acesso: **1 ano** — Preço: **Administração pública: Gratuito** — **Outras entidades: €150,00 (+IVA) / Ano** — Para mais informações: cimi@infarmed.pt»
> «O acesso só será disponibilizado após o pagamento do valor indicado.»
> 另：「A informação fornecida pelo SATS é disponibilizada às entidades que têm **protocolo de cedência de informação** com o Infarmed e integra também a base de dados de medicamentos (Infomed)…」

- **公益/非商业豁免**：页面没有公布；只能在申请中询问（信中 §4）。
- **个人开发者**：按「Outras entidades」口径很可能是 €150+VAT/年；确认是否可归入免费/减免，需书面答复。

### 1.3 CITS 交付文件（《Manual da Cedência》v16.0，16-01-2026，64 页）

- 原文：「A base de dados do Infarmed é disponibilizada num **ficheiro no formato Access, atualizado diariamente**, com uma estrutura fixa.」；有疑问联系 cimi@infarmed.pt。
- 数据模型包含（与本站映射相关）：
  - `PRODUTO`：`PROD_ID`、**`NOME`**、`DOSAGEM_CEDENCIA`/`DOSAGEM`、`FORMA_FARM_ID`、`REF_TITULAR_AIM`、`REF_ESTADO_AIM`、`REF_TIPO_AUTORIZ` 等；
  - `LNK_PROD_SUBST` + `REF_SUBSTANCIA`：**DCI/活性成分**（含 DCIPT 葡萄牙语 DCI，`REF_DCIPT`）；
  - **`REF_ATC` + `LNK_PROD_ATC`：ATC 码**（比 INFOMED 网页公开字段更全）；
  - `EMBALAGEM`（包装/CNPEM、`LNK_EMB_CNPEM`）；`REF_FORMA_FARM`（剂型）；`REF_VIA_ADMIN`（给药途径）等。
- 结论：**CITS 文件可直接支撑本站 product/variant/product_component 映射**（名称/DCI/剂量/剂型/包装/MAH/AIM 状态/ATC/CNPEM），比抓网页质量更高、更稳定；唯一问题是许可与费用。

---

## 2. 申请要点（信中已逐条覆盖)

1. **身份**：个人开发者（Pessoa Singular），非公司、无商业收入、站点免费无广告、无付费 API/数据销售。
2. **用途**：非商业公益的「商品名 → 活性成分」跨国对照；**不给用药建议、不换算剂量、不断言可互换**；每页声明非官方。
3. **请求数据**：INFOMED/CITS 事实字段（名称、DCI、dosagem、forma、apresentações、MAH、AIM 状态/商业状态、ATC、CNPEM）；machine-readable（Access/CSV/Excel）；更新频率按 CITS 每日文件或定期导出。
4. **请求许可**：公开再发布（非商业、署名 INFARMED、链回官网、不转售、不把原始文件作为独立数据集分发、不转载 FI/RCM 全文、不歪曲）。
5. **费用**：确认个人适用金额；询问公益/非商业减免；愿意在书面条款确认后支付。
6. **合规承诺**：**不爬取 INFOMED**；遵守 Guia/robots；签协议；不加官方背书暗示。
7. **退路**：若不能授权 → 不用 INFOMED；仅用 EMA 开放数据做 EU 层（署名 EMA），PT 市场保持 disabled。

---

## 3. 葡萄牙语主信（可复制发送；公开版用占位）

> **Assunto:** Pedido de cedência de informação (CITS/SATS) e autorização de reutilização pública, sem fins comerciais, de dados factuais do INFOMED

Exmos. Senhores,
Direção de Informação e Comunicação — Portal da Cedência (CITS)
INFARMED — Autoridade Nacional do Medicamento e Produtos de Saúde, I.P.

Eu, **[NOME]**, pessoa singular, com domicílio em **[LOCALIDADE]**, endereço de correio eletrónico **[E-MAIL]**, venho, por este meio, solicitar a V. Exas. o seguinte:

**1. Enquadramento**
Sou o responsável pelo projeto «Medicine Brand Cross-Reference» (https://fuornos.github.io/drug-brand-crossref/), um sítio público, gratuito, sem publicidade, sem pagamentos e sem venda de dados ou de API, que ajuda a identificar a substância ativa correspondente a um nome comercial de medicamento e a localizar produtos equivalentes noutros mercados. O projeto **não presta aconselhamento médico, não indica doses, não converte doses e não afirma que medicamentos sejam intercambiáveis**; limita-se à correspondência de identidade (nome → substância) e a avisos de «não intercambiável». O código-fonte é público em https://github.com/fuarnos/drug-brand-crossref. O sítio não é afiliado, patrocinado nem endossado pelo INFARMED.

**2. Dados pretendidos**
Solicito o acesso, ao abrigo do regime de cedência de informação de tecnologias de saúde (CITS/SATS), aos dados factuais do INFOMED relativos a medicamentos de uso humano, designadamente: **nome do produto; substância(s) ativa(s)/DCI (incluindo denominação em português); dosagem; forma farmacêutica; apresentações/embalagens; titular da AIM; número/estado da AIM e estado de comercialização; código ATC (se disponível no ficheiro de cedência); código CNPEM (se disponível)**.
Pretendo um formato **machine-readable** (o ficheiro Access disponibilizado pelo CITS, ou CSV/Excel equivalente), com a estrutura descrita no Manual da Cedência em vigor e com atualização periódica (idealmente diária, como o ficheiro CITS; aceito extrações periódicas se for essa a prática).

**3. Finalidade e forma de utilização**
A utilização será exclusivamente para: (a) indexar e pesquisar, no sítio público e gratuito, os factos acima referidos, com ligação à página oficial do INFOMED/INFARMED em cada registo; (b) produzir tabelas internas de correspondência de identidade (DCI portuguesa → INN inglês) para comparação entre mercados; (c) apresentar a informação em português (pt-PT) e, quando aplicável, noutras línguas do sítio, mantendo sempre o nome original português.

**Comprometo-me a:** (i) atribuir sempre o INFARMED/INFOMED como fonte, com a menção «Fonte: INFARMED — INFOMED (dados atualizados em AAAA-MM-DD)» e ligação à página oficial; (ii) **não vender, alugar, sublicenciar nem redistribuir o ficheiro bruto** ou uma cópia substancial dos dados como produto autónomo; (iii) não reproduzir o conteúdo do Folheto Informativo/Resumo das Características do Medicamento nem texto protegido, apenas campos factuais; (iv) não alterar os dados de forma que induza em erro; (v) indicar claramente que o sítio não é um serviço oficial e não substitui o INFOMED; (vi) cumprir os termos do protocolo de cedência que vier a ser celebrado.

**4. Condições, taxas e enquadramento**
Tenho conhecimento de que a cedência está sujeita a protocolo e de que o acesso tem a duração de 1 ano, sendo gratuito para a Administração Pública e de €150,00 (+IVA)/ano para as demais entidades. Como pessoa singular sem fins lucrativos, solicito a V. Exas. que me informem:
a) se a minha situação é elegível para o regime de cedência (registo no Portal CITS como «Pessoa Singular»);
b) qual o valor aplicável ao meu caso e se existe possibilidade de **isenção ou redução por se tratar de projeto não comercial de interesse público**;
c) se a autorização de cedência pode incluir a **reutilização pública dos campos factuais** acima descritos, com atribuição e ligação ao INFARMED, sem venda de dados;
d) qual o procedimento formal, documentos necessários, prazo estimado de resposta e forma de pagamento/faturação.
Estou disponível para pagar a taxa aplicável, caso seja devida, e para assinar o protocolo/termos que V. Exas. indiquem.

**5. Não recolha automatizada**
Para evitar qualquer dúvida: **não efetuei nem efetuarei recolha automatizada (scraping) do portal INFOMED**; respeitarei o disposto no Guia e condições de utilização e no robots.txt. É precisamente por isso que recorro à via formal de cedência.

**6. Alternativa**
Caso a cedência não seja possível, prescindirei dos dados do INFOMED e limitar-me-ei a utilizar **dados abertos da EMA** (medicamentos de autorização centralizada), com atribuição à EMA, mantendo o mercado português indisponível até obter autorização.

Agradeço a atenção de V. Exas. e aguardo uma resposta escrita, com indicação dos próximos passos. Coloco-me à disposição para prestar esclarecimentos ou enviar uma demonstração do sítio.

Com os melhores cumprimentos,
**[NOME]**
**[E-MAIL]**
**[LOCALIDADE], [DATA]**
https://fuornos.github.io/drug-brand-crossref/ · https://github.com/fuarnos/drug-brand-crossref

---

## 4. English version (for reference / optional attachment)

**Subject:** Request for CITS/SATS information cession and permission for non-commercial public re-use of factual INFOMED data

Dear Sir or Madam,
Direção de Informação e Comunicação — Portal da Cedência (CITS)
INFARMED — Autoridade Nacional do Medicamento e Produtos de Saúde, I.P.

I, **[NOME]**, an individual developer residing in **[LOCALIDADE]**, email **[E-MAIL]**, hereby request the following.

**1. Background.** I am the maintainer of “Medicine Brand Cross-Reference” (https://fuornos.github.io/drug-brand-crossref/), a free public website with no advertising, no payments and no sale of data or APIs. It helps users identify the active substance behind a brand name and find corresponding products in other markets. The site **does not provide medical advice, dosing, dose conversion or interchangeability claims**; it only maps names to substances and displays “not interchangeable” warnings. Source code: https://github.com/fuarnos/drug-brand-crossref. The site is not affiliated with, sponsored by or endorsed by INFARMED.

**2. Data requested.** Under the CITS/SATS information cession regime, I request factual INFOMED data for human medicines: product name; active substance(s)/INN (including Portuguese DCI); strength; pharmaceutical form; presentations/packages; marketing authorisation holder; marketing authorisation number/status and commercialisation status; ATC code (if included in the cession file); CNPEM code (if available). A **machine-readable format** (the CITS Access file, or equivalent CSV/Excel) with the structure described in the current Cession Manual, periodically updated (ideally daily, as the CITS file; periodic extracts acceptable).

**3. Purpose and use.** Only to: (a) index and display those factual fields on the free public site, linking each record to the official INFOMED/INFARMED page; (b) maintain internal identity-mapping tables (Portuguese DCI → English INN); (c) present information in Portuguese (pt-PT) and, where applicable, other site languages, always keeping the original Portuguese name.

**I commit to:** (i) attributing INFARMED/INFOMED as the source, e.g. “Source: INFARMED — INFOMED (data updated on YYYY-MM-DD)”, with a link to the official page; (ii) not selling, renting, sublicensing or redistributing the raw file or a substantial copy of the data as a standalone product; (iii) not reproducing package leaflets/Summaries of Product Characteristics or other protected text, only factual fields; (iv) not altering data in a misleading way; (v) clearly stating that the site is not an official service and does not replace INFOMED; (vi) complying with the cession protocol.

**4. Conditions, fees and eligibility.** I understand that cession requires a protocol, that access lasts **1 year**, is **free for public administration** and costs **€150.00 (+VAT)/year for other entities**. As a non-profit individual, please confirm: (a) whether I am eligible via CITS registration as “Pessoa Singular”; (b) the applicable fee and whether **an exemption or reduction for a non-commercial public-interest project** is possible; (c) whether the cession can include **public re-use of the factual fields** described above, with attribution and link-back, without data selling; (d) the formal procedure, required documents, expected response time and payment/invoicing arrangements. I am willing to pay the applicable fee, if due, and to sign any protocol/terms you indicate.

**5. No automated collection.** I have not performed and will not perform automated scraping of the INFOMED portal; I will respect the Guide and Terms of Use and robots.txt. That is precisely why I am applying through the formal cession route.

**6. Alternative.** If cession is not possible, I will not use INFOMED data and will rely solely on **EMA open data** (centrally authorised medicines) with EMA attribution, keeping the Portuguese market unavailable until authorisation is obtained.

Thank you for your consideration. I look forward to your written reply and remain available for any clarification or to provide a demonstration of the website.

Yours faithfully,
**[NOME]**
**[E-MAIL]**
**[LOCALIDADE], [DATA]**
https://fuornos.github.io/drug-brand-crossref/ · https://github.com/fuarnos/drug-brand-crossref

---

## 5. 中文版（自留/可附）

**主题：** 申请 CITS/SATS 数据让与（cedência）及 INFOMED 事实数据的非商业公开再发布许可

尊敬的 INFARMED 信息与传播部门 / CITS 数据让与门户：

本人 **[姓名]**，个人开发者，居住地 **[城市]**，邮箱 **[邮箱]**，现提出以下申请：

**1. 背景**：本人维护公益网站「Medicine Brand Cross-Reference」（https://fuornos.github.io/drug-brand-crossref/），免费、无广告、无付费、不售卖数据/API；用途是识别商品名对应的活性成分，并定位其他国家的对应产品。网站**不提供用药建议、不做剂量换算、不判断可互换**，只做身份对应与「不可互换」提示。代码公开于 https://github.com/fuarnos/drug-brand-crossref；与 INFARMED 无隶属、赞助或背书关系。

**2. 申请数据**：INFOMED 人用药品事实字段——商品名、活性成分/DCI（含葡语名）、规格/剂量、剂型、包装/规格、MAH、AIM 编号/状态与商业状态、ATC（若让与文件包含）、CNPEM（若有）；机器可读格式（CITS Access 文件或等价 CSV/Excel）；按现行《让与手册》结构，定期更新（最好每日，如 CITS 文件；定期导出亦可）。

**3. 用途与承诺**：仅用于 (a) 在免费公开网站索引/展示上述事实，并逐条链接 INFOMED/INFARMED 官方页面；(b) 建立「葡语 DCI→英文 INN」内部身份映射；(c) 以葡语（pt-PT）及站点其他语言展示，但保留葡语原名。承诺：署名 INFARMED/INFOMED（如「来源：INFARMED — INFOMED，数据更新于 AAAA-MM-DD」）并链回官网；不出售/出租/转授权/把原始文件或实质性副本作为独立数据集再分发；不转载说明书/RCM 全文，只使用事实字段；不歪曲数据；明确本站非官方服务、不替代 INFOMED；遵守让与协议。

**4. 费用与资格**：已知让与需签协议、访问期 1 年、公共行政部门免费、其他机构 €150（+IVA）/年。作为非营利个人，请确认：(a) 是否可通过 CITS 以「Pessoa Singular（个人）」申请；(b) 本人适用费用，以及**非商业公益项目能否豁免/减免**；(c) 让与是否可包含上述事实字段的**公开再发布**（署名+链回、不售卖数据）；(d) 正式流程、所需材料、预计答复时间和付款/开票方式。如应缴费，本人愿意在书面条款确认后支付，并签署相关协议。

**5. 不进行自动抓取**：本人未且不会对 INFOMED 进行自动爬取，遵守 Guia/使用条款与 robots.txt；因此走正式让与渠道。

**6. 替代方案**：若无法让与，本人将不使用 INFOMED 数据，仅使用 EMA 集中审批开放数据（署名 EMA），在获得授权前不开放葡萄牙市场。

期待书面答复与下一步指引，感谢！

此致
**[姓名]**
**[邮箱]**
**[城市]，[日期]**
https://fuornos.github.io/drug-brand-crossref/ · https://github.com/fuarnos/drug-brand-crossref

---

## 6. 提交与跟进

1. **先注册 CITS**：https://extranet.infarmed.pt/CITS-fo/registo.jsf → 「Pedido de acesso」→ 选择 **Pessoa Singular**，填写身份/联系方式；如注册遇到问题，邮件 cimi@infarmed.pt 说明。
2. **发主信**（葡文优先）到 **cimi@infarmed.pt**，主题用下方 Assunto；可抄送 `infarmed@infarmed.pt`；附件可选：英文版、站点截图/链接（不附数据、不附个人信息表）。
   - Assunto: `Pedido de cedência CITS/SATS — reutilização pública não comercial de dados factuais do INFOMED`
3. **等待书面答复**（建议 10 个工作日；2 周无回复可礼貌跟进一次）。**在收到书面费用/转载条款前不付款**。
4. 若答复要求走 CITS 门户流程：按门户表单提交申请，附上本信；如提供协议模板，逐条确认「公开再发布/署名/链回/不转售」写入。
5. 拿到授权后：把 Access/CSV 文件放在 `data/raw/pt/`（不进公开仓库），按 `reports/pt-audit.md` §2 写 `etl/`（dry-run 先行），再按 task-92 建议开 PT country / pt-PT UI。
6. **退路**：被拒/费用不合适/条款不允许公开再发布 → 回 EMA 层（`data/raw/pt/ema_medicines_report_en.xlsx` 已在缓存），PT 市场保持 disabled；pt-PT UI 与 EU region 仍可先做。

---

## 7. 证据与引用

| 证据 | URL / 文件 |
|---|---|
| CITS 门户首页 | https://extranet.infarmed.pt/CITS-fo/ （HTTP 200） |
| CITS 注册/申请表单（Pessoa Singular/Coletiva） | https://extranet.infarmed.pt/CITS-fo/registo.jsf （HTTP 200） |
| 官方让与说明页 | https://www.infarmed.pt/web/infarmed/profissionais-de-saude/prescricao-e-dispensa/cedencia-de-base-de-dados-de-medicamentos |
| 同主题说明页 | https://www.infarmed.pt/web/infarmed/cedencia-de-bases-de-dados-de-medicamentos |
| 《Manual da Cedência》v16.0（2026-01-16，64 页，Access 交付/每日更新/字段） | 本地缓存 `.tmp/pt-request/cits_manual_webservices`（PDF，1,644,406 B），文本 `.tmp/pt-request/cits_manual.txt` |
| 联系 | cimi@infarmed.pt；+351 21 798 7373；Parque de Saúde de Lisboa, Av. do Brasil 53, 1749-004 Lisboa |
| INFOMED 禁爬/许可 | `reports/pt-audit.md` §1.1（Guia + robots.txt `Disallow: /`） |
| EMA 退路 | `reports/pt-audit.md` §1.4（EMA legal notice 可复制/分发行，须署名；XLSX 2,754 行已缓存 `data/raw/pt/ema_medicines_report_en.xlsx`） |

## 8. 注意与风险

- **公开版不含个人信息**：本报告只用占位；真名/邮箱只在 `.tmp/pt-request/application-filled.md`（本地，勿提交公开仓库）。
- **不要先付款**：先拿到书面「费用 + 公开再发布许可 + 协议条款」再决定；个人可能按「Outras entidades」收费，需确认。
- **不要抓取**：robots/Guia 禁止；本信主动承诺不爬取，避免被直接拒绝。
- **转载权是核心**：即使拿到数据文件，若协议仅允许内部使用，仍不能上站；务必把「公开非商业网站展示 + 署名 + 链回 + 不转售」写进书面答复/协议。
- **Fallback 已固定**：未授权 → EMA 层 + PT disabled；不拿 INFOMED 数据做「先上线后补授权」。
- 本材料**不是法律意见**；若 INFARMED 要求正式协议/法务审查，由用户决定是否签署。
