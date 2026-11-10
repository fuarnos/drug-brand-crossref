# 许可请求草稿 · 荷兰 CBG-MEB 药品信息库（GIP）

> 状态：**已发送 2026-11-11（主收件人无退信，未确认投递/受理）；本文件为发出定稿存档**（署名处 `<naam / organisatie / contactadres>` 由用户填写，未回填）。
> 背景与判断依据：`reports/2026-11-11-nl-license-assessment.md`。
> 用途：仅申请「事实字段再发布」许可，不涉及说明书全文、不涉及用药建议、不涉及商业化。

## 收件人 / 主题

- 收件人：`Geneesmiddelgebruik@cbg-meb.nl`（国家数据目录登记的联系点），抄送 `info@cbg-meb.nl`（若公开）
- 主题（NL）：`Verzoek om hergebruik van de Geneesmiddeleninformatiebank (metadata.csv)`
- 主题（EN）：`Request for re-use permission: Geneesmiddeleninformatiebank data file (metadata.csv)`

## 正文（荷兰语）

Geachte heer/mevrouw,

Wij beheren een niet-commerciële, openbare referentiesite over geneesmiddelen (geen advertenties, geen verkoop, geen account) die namen van geneesmiddelen koppelt aan werkzame stof, farmaceutische vorm en sterkte, en die per product verwijst naar de oorspronkelijke bron.

In de catalogus van data.overheid.nl staat de dataset *Geneesmiddeleninformatiebank* (dataset-id `87bf9724-971f-5bfc-82de-f2aef049bbd4`) geregistreerd met de licentie `licentieonbekend`. Op de website van de Geneesmiddeleninformatiebank zelf hebben wij geen gebruiks- of licensievoorwaarden kunnen vinden. Daarom vragen wij u vriendelijk:

1. of hergebruik van het databestand `metadata.csv` is toegestaan;
2. zo ja, onder welke voorwaarden (naamsvermelding, bron-URL, datum van de dataset, geen logo's, geen wijziging van velden, geen bulkverspreiding van het bestand zelf);
3. zo nee, of u kunt aangeven welke velden wél gepubliceerd mogen worden (bijvoorbeeld alleen registratienummer, productnaam, werkzame stof, ATC-code, farmaceutische vorm en sterkte, met een link naar de productpagina in de Geneesmiddeleninformatiebank).

Ons gebruik zou als volgt zijn: wij nemen uitsluitend **feitelijke velden** op (registratienummer, productnaam, houder, farmaceutische vorm, sterkte, toedieningsweg, ATC-code, werkzame stoffen). Wij publiceren het bestand zelf niet, wij wijzigen geen veldwaarden, wij voegen geen logo's toe en wij suggereren geen goedkeuring door het CBG. Bij elk product verwijzen wij naar de oorspronkelijke productpagina. Wij geven geen medisch advies, geen doseringsadvies en geen vervangingsadvies.

Graag ontvangen wij uw reactie, of een verwijzing naar de juiste afdeling.

Met vriendelijke groet,
\<naam / organisatie / contactadres\>

## 正文（英语，附在同一封邮件后半）

Dear Sir or Madam,

We run a non-commercial public reference site that maps medicine brand names to active substance, pharmaceutical form and strength, and links every product back to its original source (no advertising, no sales, no accounts).

The dataset *Geneesmiddeleninformatiebank* (data.overheid.nl id `87bf9724-971f-5bfc-82de-f2aef049bbd4`) is registered with the licence `licentieonbekend`, and we could not find any terms of use on the Geneesmiddeleninformatiebank website. We would like to ask:

1. whether re-use of the `metadata.csv` data file is permitted;
2. if so, under which conditions (attribution, source URL, dataset date, no logos, no alteration of field values, no redistribution of the file itself);
3. if not, which fields may be published (e.g. registration number, product name, holder, pharmaceutical form, strength, route, ATC code, active substances) with a link to the product page.

Our use would be limited to **factual fields** only. We would not redistribute the file, not alter field values, not add logos, and not imply endorsement by CBG-MEB. Every product links back to its original page. We provide no medical, dosing or substitution advice.

Thank you for your consideration.

Kind regards,
\<name / organisation / contact address\>

## 发出后的动作

1. `docs/跟进提醒.md` 已有 11-25 / 12-09 两个节点；答复到达后更新 `docs/许可清单.md` §2.10 与队列。
2. 若获批（含条件）：按条件改 `etl/markets/nl.py` 的输出字段 → 干跑核数 → 第二个 DB 窗口写入 → 开 `nl` 语言 → v0.11.x 发布。
3. 若被拒或长期无答复：NL 保持「事实 + 链接」的候选状态，`nl` 语言继续 `enabled:false`，不空开字典。
