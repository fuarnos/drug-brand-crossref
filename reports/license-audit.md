# 数据许可清单 + About 署名审计

> 日期：2026-10-27 ｜ 任务：`task-26` ｜ 站点版本：v0.3.5
> 产物：`docs/许可清单.md`（权威登记处）+ 本报告 + `.tmp/license/` 证据
> 边界：只读 `site/build.py` 与 `data/drugs.db`；**未改** `site/build.py`、未写库、未跑 git / `site/build.py` / 发布。

## 0. 结论（先说答案）

1. **`source` 表 27 个来源中，About 完整覆盖 15 个，其余 12 个有缺口**：4 个点名但许可缺失（CN/ES/MX/AU-TGA），4 个 CC BY 4.0 数据集完全未提，3 个 ARTG 明细来源未披露，1 个人工种子只披露了 1 条。另有 **WHO INN 数据文件已在仓库公开但 About 零署名**、**ChEMBL 未接入但排在 ATC 补全队列** 两个前置缺口。
2. **最高风险 3 条**（详见 §3）：
   - **WHO INN / CC BY-NC-SA 3.0 IGO**：`data/who_inn_names.csv` 已随仓库公开，About 无署名、无非商业声明、无 share-alike 说明 → 义务已生效却未履行；
   - **TGA CMI + ARTG 明细 / TGA copyright**：TGA 条款只允许个人/内部非商业使用与不改动复制，**明确不允许再传输/分发**；本站已用 4,730 + 1,559 + 144 条产品，About 只字未提版权，且 ARTG 明细层未披露 → 再分发依据最弱；
   - **中国 NHSA / 未找到再发布许可**：146,344 条产品（最大市场），About 只写来源不写法律状态 → 需显式声明「未找到开放许可、只存事实 + 链原文」。
3. **ES / MX 均维持「待确认」**：AEMPS Aviso legal 允许「复制须注明出处 + 最后更新日期」，属条件性引用而非开放许可；COFEPRIS/gob.mx 未标注开放许可。**均需法务/书面确认后才可升级**。
4. **ChEMBL = CC BY-SA 4.0（share-alike）**：一旦 ATC 映射进对外数据，派生映射表须同许可公开并署名；**WHO INN = CC BY-NC-SA 3.0 IGO（非商业 + 署名 + SA）**。两条已写进 `docs/许可清单.md` §3 的「接入前必须做」。
5. **建议的三语署名段落可直接接入 `build_about()`**（纯 HTML，无新依赖，见 §4）；但需由有写权限的建站会话改一次 `site/build.py` 并重建验收——本任务不碰 `site/build.py`。

## 1. 口径与证据

- **来源清单**：`data/drugs.db` 的 `source` 表（27 行，只读 URI 打开）；产品来源分布、`corroboration` 的 CC-BY 佐证 URL 一并导出到 `.tmp/license/source_table.txt` / `.json`。
- **About 现状**：`site/build.py` 的 `build_about()`（审计时刻为 2026-10-27 09:5x，函数起 L2069、数据来源段 L2168–L2241、已知缺口段 L2251–L2278；文件正被并行任务改动，行号会漂移）。原文摘录：`.tmp/license/about_current_extract.txt`。
- **仓库既有许可结论**：`docs/方案与数据模型.md` §6、`reports/opensource-drug-data-20261026.md`、`reports/who-inn-20261026.md` §2、`data/sources/README.md`、`docs/foi-artg-request.md`。
- **本轮新核**（web）：openFDA 许可页（CC0）、TGA copyright（Wayback 2025-01-18 快照，站点直连 403）、AEMPS Aviso legal（复制须注明出处 + 更新日期）、Health Canada DPD 首页（条款页旧链接无法复核）。证据链接见 `docs/许可清单.md` 与 `.tmp/license/web_evidence.md`。
- **计数**：product 409,485 / substance 12,793 / source 27；各市场产品数见 `docs/许可清单.md` §2。DB 与 `site/build.py` 正被其它任务并发更新，数字以本报告生成时为准。

## 2. About 现状审计（逐来源）

About 的「Sources and coverage 数据来源与覆盖」段当前覆盖情况：

| 状态 | 数量 | 来源 |
|---|---|---|
| ✅ 完整（来源 + 许可/署名） | 15 | openfda_ndc、dmd、pbs、hc_dpd、wikidata_atc_p267、nida_slang、dea_slang、medlineplus、fda_tml、issste_catalogo、profeco_precios、community_cn、frank_uk、adf_au、pnsd_es |
| 🟡 点名但许可/署名缺失 | 4 | **nhsa**（无许可声明）、**cima**（无署名/更新日期）、**cofepris_mx**（无许可状态）、**tga_cmi**（无 TGA 版权/非商业） |
| ❌ 完全未覆盖 | 4 | **hgmgg_ccby、iner_ccby、inprfm_ccby、semar_ccby**（CC BY 4.0，MX 规格回填，共 728 条佐证） |
| ❌ 覆盖弱/未披露 | 3 | **artg_index、artg_detail、artg_enrich**（About 只说 ARTG 无批量文件，未披露已用 1,703 条 ARTG 明细产品、无 © Commonwealth 声明） |
| 🟡 部分披露 | 1 | **manual_seed**（只披露 Gaviscon 手录；CN/GB 人工种子未说明） |
| 未接入但需提前声明 | 2 | **WHO INN**（文件已公开）、**ChEMBL**（计划补 ATC） |

其他结构性发现：
- About **只有英/中双语**，无西语段；而 ES 是已上线的市场（25,293 产品）——西语用户看不到许可/署名说明。
- About **没有「许可清单」入口**，也没有统一的「只存事实字段、不转载正文」政策声明。
- `source.license_url` **9/27 为空**（adf_au、community_cn、fda_tml、frank_uk、manual_seed、medlineplus、nhsa、nida_slang、pnsd_es），审计不可追溯。
- TGA/ARTG 的 `license_url` 已指向 `tga.gov.au/copyright`，但 About 未引用该声明；Health Canada 的条款链接是旧地址（`healthycanadians.gc.ca/important-eng.php#a6`），本轮无法复核。

## 3. 缺口清单（12 项）与最高风险 3 条

| # | 等级 | 缺口 | 影响 | 建议修法 |
|---|---|---|---|---|
| G1 | **高** | WHO INN 数据已进仓库（`data/who_inn_names.csv`，1,737 行）但 About 无署名/非商业/SA | 违反 CC BY-NC-SA 3.0 IGO；若商业化风险升级 | About 新增 WHO 段（§4 文本）；派生映射按 CC BY-NC-SA 共享；声明 WHO 未背书 |
| G2 | **高** | TGA CMI + ARTG 明细来源无版权/非商业声明，ARTG 明细层未披露 | TGA 条款不允许未授权再分发；站点再分发依据最弱 | About 澳洲段补 © Commonwealth of Australia、非商业、仅事实字段；披露 ARTG 明细层；必要时走 FOI（草稿已有） |
| G3 | **高** | 中国 NHSA 未写「未找到再发布许可」 | 最大市场 146,344 条产品的法律状态未披露 | About 中国段加一句事实+链接声明（§4 文本） |
| G4 | 中 | ES CIMA 无署名/来源/更新日期 | AEMPS Aviso legal 的引用条件未满足 | About 西班牙段补 AEMPS 署名 + 许可链接 + 「最后更新日期」；标注待确认 |
| G5 | 中 | MX COFEPRIS 无许可状态（待确认未写明） | 用户/法务无法判断再发布边界 | About 墨西哥段补「未标注开放许可，仅事实 + 链接，待确认」 |
| G6 | 中 | 4 个 datos.gob.mx CC BY 4.0 数据集（hgmgg/iner/inprfm/semar）未在 About | CC BY 的署名义务未履行；About 只写 2/6 | About 墨西哥段列出 6 个数据集名 + CC BY 4.0 链接 |
| G7 | 中 | ChEMBL 若接入 ATC 需 CC BY-SA 4.0 声明与 share-alike 方案 | 未声明即分发会违反 SA | 接入前置条件写入 `docs/许可清单.md` §3；About 预留 ChEMBL 段 |
| G8 | 中 | About 无西语段、无「许可清单」入口、无统一「只存事实」政策 | 西语市场看不到义务说明；审计不可追溯 | 新增「Data sources and licences」小节（三语，§4）+ 链 `docs/许可清单.md`（GitHub blob 或后续 `licences.html`） |
| G9 | 低 | 社区来源（frank_uk / adf_au / pnsd_es / community_cn）只有链接、无版权措辞 | 署名义务不完整（Crown copyright / © ADF / 政府文件） | About 社区列表补一句「逐条署名，只存叫法事实」 |
| G10 | 低 | Health Canada DPD 条款页旧链接 404，About 直接断言「非商业再使用」 | 依据不可复核 | 更新 `source.license_url` 为可访问条款页并复核措辞 |
| G11 | 低 | `source.license_url` 9/27 为空 | 审计/自动化无法校验 | 回填 9 条（清单见 `.tmp/license/source_table.txt`） |
| G12 | 低 | manual_seed 只披露 Gaviscon，CN/GB 人工种子未说明 | 披露不完整 | About 加半句「其他人工种子逐条带 source_url」 |

**最高风险 3 条 = G1 / G2 / G3**（均需在下次发布前修，且 G1/G2 属「义务已发生」而非「将来接入」）。

## 4. 建议的三语署名段落（可直接接入 `build_about()`）

> 用法：整段为纯 HTML（无 `{}`，可原样放进 About 的 f-string）。建议插在 `<h2>Sources and coverage 数据来源与覆盖</h2>` 表格之后、`Known gaps` 之前；来源细节与链接以 `docs/许可清单.md` 为准。

```html
<h2 id="licences">Data sources and licences 数据来源与许可 Fuentes y licencias</h2>
<p class="sub"><b>EN</b>: This site is a non-commercial public reference. We store only factual
fields (names, active ingredients, strengths, dosage forms, status) and link to the originals;
we do not republish full labels, CMI/SmPC texts or data dumps. Source-specific terms and
attribution are listed in the <a href="https://github.com/fuarnos/drug-brand-crossref/blob/main/docs/%E8%AE%B8%E5%8F%AF%E6%B8%85%E5%8D%95.md">licence register</a>.
<br><b>中文</b>：本站为非商业公开参考站，只存事实字段（名称、成分、规格、剂型、状态）并链回原文，
不转载说明书 / CMI / SmPC 全文，也不提供原始数据批量下载。各来源许可与署名见
<a href="https://github.com/fuarnos/drug-brand-crossref/blob/main/docs/%E8%AE%B8%E5%8F%AF%E6%B8%85%E5%8D%95.md">许可清单</a>。
<br><b>ES</b>: Este sitio es una referencia pública sin ánimo de lucro. Solo almacenamos campos
fácticos (nombres, principios activos, concentraciones, formas farmacéuticas, estado) y enlazamos
al original; no reproducimos prospectos, textos CMI/SmPC ni volcados de datos. Las condiciones y
atribuciones por fuente están en el <a href="https://github.com/fuarnos/drug-brand-crossref/blob/main/docs/%E8%AE%B8%E5%8F%AF%E6%B8%85%E5%8D%95.md">registro de licencias</a>.</p>
<ul class="sub">
<li><b>China 中国 / China</b>: 医保药品分类与代码数据库由<b>国家医保局</b>公开；我们<b>未找到开放的再发布许可</b>，
只存事实字段并链回原文，不再发布原始数据表。EN: the NHSA catalogue is public but we found
<b>no open licence for redistribution</b>; factual fields only, with links, no bulk republication.
ES: el catálogo de la NHSA es público, pero <b>no hemos encontrado una licencia abierta de
redistribución</b>; solo campos fácticos y enlaces. 来源 Source: <a href="https://code.nhsa.gov.cn/yp/toPublicGoodsData.html">code.nhsa.gov.cn</a></li>

<li><b>Spain 西班牙 / España</b>: © <b>AEMPS</b> — CIMA (Centro de Información online de
Medicamentos). Reproduction of AEMPS website contents is authorised provided the source is
expressly cited and the <b>date of last update</b> is mentioned (Aviso legal). This is not an open
licence; we treat it as "conditional / pending confirmation". 中文：© AEMPS，引用须注明来源与文件最后更新日期，
非开放许可，按「待确认」处理。ES: © AEMPS — se autoriza la reproducción citando expresamente la
fuente y la fecha de última actualización (Aviso legal); no es una licencia abierta.
<a href="https://www.aemps.gob.es/aviso-legal/">Aviso legal</a> · <a href="https://cima.aemps.es/cima/publico/home.html">CIMA</a></li>

<li><b>Mexico 墨西哥 / México</b>: COFEPRIS registration lists published on gob.mx carry
<b>no stated open licence</b> (status: pending confirmation); we store factual fields only and
link to the source. Strengths were back-filled from <b>ISSSTE, PROFECO, HGMGG, INER, INPRFM and
SEMAR</b> procurement/price datasets published on <b>datos.gob.mx</b>, licensed <b>CC BY 4.0</b>
(attribution: Gobierno de México — datos.gob.mx, each dataset attributed to its publishing
institution). 中文：COFEPRIS 清单未标注开放许可，按「待确认」只存事实 + 链接；规格回填数据来自
datos.gob.mx 的 ISSSTE/PROFECO/HGMGG/INER/INPRFM/SEMAR 数据集（CC BY 4.0，署名发布机构）。
ES: las listas de COFEPRIS no declaran licencia abierta (pendiente de confirmación); solo campos
fácticos y enlaces. Los datos de concentración proceden de ISSSTE, PROFECO, HGMGG, INER, INPRFM y
SEMAR en datos.gob.mx, con licencia CC BY 4.0.
<a href="https://www.gob.mx/cofepris/documentos/registros-sanitarios-medicamentos">COFEPRIS</a> ·
<a href="https://datos.gob.mx/">datos.gob.mx</a> ·
<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a></li>

<li><b>Australia 澳洲 / Australia</b>: PBS Schedule data — <i>Copyright (c) 2024 Department of
Health, Commonwealth of Australia.</i> (copyright notice retained; content not modified).
TGA CMI repository and ARTG Public Summary entries — <b>© Commonwealth of Australia</b>; the TGA
copyright notice permits personal/internal non-commercial use of unaltered material and does not
permit re-transmission or redistribution without written permission, so we store <b>factual
fields only</b> (trade name, active ingredients, ARTG ID, status) with links and publish no
full-text CMI/ARTG content. 中文：PBS 保留版权声明且不修改内容；TGA CMI 与 ARTG 明细只取事实字段
（商品名/成分/ARTG ID/状态）并链回原文，不转载 CMI 全文、不再分发原始材料。
ES: datos PBS con aviso de copyright intacto y sin modificaciones; de TGA CMI y ARTG solo
almacenamos campos fácticos con enlaces, sin reproducir textos completos.
<a href="https://www.health.gov.au/using-our-websites/copyright">PBS copyright</a> ·
<a href="https://www.tga.gov.au/copyright">TGA copyright</a></li>

<li><b>Canada 加拿大 / Canadá</b>: Health Canada <b>Drug Product Database (DPD)</b> — re-use for
non-commercial purposes with source acknowledgement: <i>© His Majesty the King in Right of Canada,
as represented by the Minister of Health.</i> 中文：仅非商业再使用，须注明来源（加拿大卫生部）。
ES: reutilización no comercial con mención de la fuente. Terms: <a href="https://health-products.canada.ca/dpd-bdpp/">DPD</a></li>

<li><b>WHO INN / OMS</b>: Contains International Nonproprietary Names (INN) data from the
<b>World Health Organization</b>. WHO INN lists are licensed <b>CC BY-NC-SA 3.0 IGO</b>
(attribution + non-commercial + share-alike); this site is non-commercial, and any mapping table
derived from WHO INN lists is shared under the same licence. WHO does not endorse this site.
中文：含世界卫生组织 INN 数据；WHO INN 清单为 CC BY-NC-SA 3.0 IGO（署名 + 非商业 + 相同方式共享），
基于该清单的派生映射表以同许可共享；WHO 未背书本站。
ES: contiene datos de INN de la Organización Mundial de la Salud; las listas INN tienen licencia
CC BY-NC-SA 3.0 IGO (atribución + no comercial + compartir igual); los mapeos derivados se
comparten con la misma licencia. <a href="https://www.who.int/teams/health-product-and-policy-standards/inn">WHO INN</a> ·
<a href="https://creativecommons.org/licenses/by-nc-sa/3.0/igo/">CC BY-NC-SA 3.0 IGO</a></li>

<li><b>ChEMBL</b> (only after ATC data from ChEMBL is published): ATC mapping derived from
<b>ChEMBL (EMBL-EBI)</b>, licensed <b>CC BY-SA 4.0</b>; the derived ATC mapping table is available
under the same licence. 中文：若对外发布基于 ChEMBL 的 ATC 映射，须署名 EMBL-EBI 并按 CC BY-SA 4.0
相同方式共享。ES: mapeo ATC derivado de ChEMBL (EMBL-EBI), licencia CC BY-SA 4.0; la tabla derivada
se comparte con la misma licencia. <a href="https://chembl.gitbook.io/chembl-interface-documentation/downloads">ChEMBL</a> ·
<a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a></li>

<li><b>Other sources 其他来源</b>: openFDA (public domain / CC0), FDA tall-man list (US Government
work), NIDA (US Government work), DEA (Public Domain Mark 1.0), MedlinePlus/NLM (US Government
work), NHSBSA dm+d (Open Government Licence v3.0 — <i>Contains public sector information licensed
under the Open Government Licence v3.0.</i>), Wikidata P267 (CC0 1.0). ISMP/ECRI LASA lists and
WHOCC ATC/DDD index are copyrighted and are <b>not</b> reproduced. 中文：其余来源见许可清单；ISMP/ECRI
与 WHOCC ATC/DDD 有版权，未使用。
ES: el resto de fuentes figura en el registro de licencias; las listas ISMP/ECRI y el índice
WHOCC ATC/DDD no se reproducen.</li>
</ul>
<p class="sub"><b>Non-commercial notice 非商业声明</b>: this site is public, ad-free and offers no
paid data service; if that changes, the NC/conditional sources above must be re-evaluated.
本站公开、无广告、不提供付费数据服务；如未来商业化，上述标非商业/待确认的来源须重新评估。</p>
```

**可直接接入吗？** 可以——上述文本为纯 HTML、无新增依赖、无 f-string 花括号，按原样替换/插入即可；
需一次 `site/build.py` 改动 + `python site/build.py` 重建验收（本任务写范围不含 `build.py`）。
两点注意：① 链接用 GitHub blob 需对中文文件名做 percent-encoding（上面已编码）；更稳的做法是后续由建站任务生成 `licences.html`；② About 目前无西语版，本段以同页三语并排方式接入，避免等 i18n 改造。

## 5. 建议改动顺序（交给有写权限的会话）

1. **P0（发布前必须）**：接入 §4 文本中的 CN / TGA-ARTG / WHO 三段（G1–G3）；
2. **P1**：ES / MX / 4 个 CC-BY 数据集（G4–G6）+ 西语段落（G8）；
3. **P2**：社区来源版权措辞（G9）、DPD 条款链接复核（G10）、`source.license_url` 回填（G11）、manual_seed 披露（G12）；
4. 接入 ChEMBL 前先完成 G7 的声明与 share-alike 导出方案。
5. 验收：`python site/build.py` 到 `== done ==`；About 三语段落渲染正常；`docs/许可清单.md` 与 About 列表逐行一致（可用脚本比对来源 ID/名称）。

## 6. 证据索引（`.tmp/license/`）

| 文件 | 内容 |
|---|---|
| `source_table.txt` / `source_table.json` | `source` 表 27 行（license/license_url/url/data_as_of）+ 产品来源分布 + artg_entry 分布 |
| `repo_facts.txt` | corroboration 的 CC-BY 佐证 URL（issste 2,837 / profeco 286 / hgggg 391 / inprfm 277 / semar 39 / iner 21）+ 派生数据文件表头（who_inn_names.csv 含 license 列） |
| `about_current_extract.txt` | `site/build.py` About 数据来源段原文（行号摘录） |
| `web_evidence.md` | 本轮 web 核对：openFDA CC0、TGA copyright、AEMPS Aviso legal、Health Canada DPD、ChEMBL/WHO 既有证据 |
| `probe_sources.py` / `probe_repo_facts.py` / `probe_about.py` | 上述数据的只读复现脚本 |

复现：
```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\license\probe_sources.py
& $py .tmp\license\probe_repo_facts.py
& $py .tmp\license\probe_about.py
```

_本报告为只读审计产物：未改 `site/build.py`、未写 `data/drugs.db`、未跑 git / 发布。_
