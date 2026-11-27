# LANG1-B（v1.2.9）本地文字主名「回源」可行性评估 —— KR / HK / JP

- 日期：2026-11-28（北京）｜工位：**data-scout**（`task-5`）｜会话：谷段交付（只读评估）
- 范围：**只读**。未改代码 / 注册表 / 库 / `site/dist`，未抓数据，未 commit；分析脚本只在 `.tmp/`。
- 基线：`data/drugs.db` 现查 **731,078 产品 / 369,829 `name_key`**；`site/dist` 为 2026-11-26 构建产物（`core.json` **67,963,821 B raw / 13,321,117 B gzip**，362,502 行）。
- 行号说明：文中 `site/build.py` / `etl/normalize_name.py` / `db/consistency_audit_identity.py` 的行号按 **2026-11-28 读取时 HEAD**；若 v1.2.8 改动导致漂移，以**函数名**为准。
- 结论先行，所有数字可用 §8 的命令复现；失败与缺口集中在 §7。

---

## 0 结论先行

> **LANG1-B 的前提需要更正**：Lead 现查的「KR 97,317/97,356 是拉丁文、JP 无假名」来自 **`name_key.script` 列**（`docs/谷段需求队列.md:33` 写明了这个口径），而 `script` 是归一化标签，**不是主名文字**。KR/JP 的本地文字主名**已经在库、已在站上**；HK 才是真的「源里没有」。

| 市场 | 源里真的有本地文字商品名字段吗 | 是否已入库 | 许可（只引用现有结论） | v1.2.9 结论 |
|---|---|---|---|---|
| **KR** | **有**：HIRA 약가마스터 `한글상품명`，309,888/309,889 行含韩文 | **已入库**：97,316/97,340 个主名是韩文（23 汉字、1 拉丁、16 品目无名） | ✅ 공공누리 제1유형（`docs/许可清单.md` §2.16，`source_id=hira_kr_medprice` 已在库） | **不需要回源**；修 `script` 标签 + 客户端韩文检索（§1.3 / §4） |
| **JP** | **有**：薬価基準 `品名`，12,442 个主名全是日文（12,191 含假名〔norm 口径；raw 口径 12,193〕，251 纯汉字） | **已入库** | ✅ PDL 1.0（§2.15，`source_id=jp_yakka` 已在库） | **不需要回源**；只需回填 1,184 个纯假名 key 的 `script` 标签 |
| **HK** | **无**：DrugList.xml 只有英文 `productName`；data.gov.hk 资源标题明写 **“(English Only)”**、`inLanguage=English`；DH 搜索页标题「只提供英文版本」 | 已入库英文名 13,935 个；CJK 名 0 | 🟡 现源 data.gov.hk T&C 允许免费再发布（须署名，§2.9）；**任何新源必须先做许可登记**（AGENTS §4） | **需另找源**；本轮未找到开放、批量、商品级的官方繁中名源 → **人拍板**（§2.3 / §6-L4） |

**直接回答「是否必须先做 T10」**：

- **按 v1.2.9 的最小口径（本报告 §4 方案 A：0 个新增名字行）→ 不必先做 T10**，`core.json` 一个字节都不变（68.0 / 13.32 MB，护栏 80/16）。
- 若把 **HK 繁中商品名**纳入（+≈1.4 万行）：core raw ≈ **70.86 MB = 88.6%**、gzip ≈ **13.79 MB = 86.2%**，仍 ≤80/16 但已越过 85% 线 —— 按 AGENTS §6「下一次接近上限前先分片」**建议同版做 T10**；还会新增 ≈1.4 万个名字页（≈+14k PUT / +≈100 MB dist）。
- 若补 **KR 拉丁/英文名**（+≈9.7 万行，只能走 MFDS Route A 账号墙）：core raw ≈ **88.19 MB = 110.2%**、gzip ≈ **16.60 MB = 103.8%** —— **必须先做 T10**，且会新增 ≈9.7 万个名字页（≈+97k PUT / +≈0.7 GB dist），不属于 v1.2.9。

**用户可见的真实缺口（已复现，P0）**：浏览器输入「간포트점안액」→「일치 없음 / no match」；同一名字 `cli.py` 命中 `KR-200805356`。JP「ユーロジン散1%」浏览器正常，中文「泰诺」正常。根因是客户端 `norm()` 产出 NFC、索引键是 NFD Jamo（§1.3）。

---

## 1 关键更正：`name_key.script` ≠ 主名文字

### 1.1 Lead 的现查数字（`script` 列）复现

```sql
-- db/q.py
SELECT p.country, k.script, COUNT(*) n
FROM product p
JOIN product_name pn ON pn.product_id=p.product_id
     AND pn.name_type='trade' AND pn.is_primary=1
JOIN name_key k ON k.key_id=pn.key_id
WHERE p.country IN ('KR','HK','JP','CN','TW')
GROUP BY 1,2;
```

结果（2026-11-28 现查）：

| country | latin | han | kana | hangul |
|---|---:|---:|---:|---:|
| KR | **97,317** | 23 | 0 | 0 |
| HK | **13,935** | 0 | 0 | 0 |
| JP | **1,428** | **11,014** | 0 | 0 |
| CN | 35 | 18,300 | 0 | 0 |
| TW | 0 | 16,453 | 0 | 0 |

这就是 `docs/谷段需求队列.md:33` 的「数据侧主名文字（`name_key.script` 现查）」；数字能对上，但**它描述的是标签，不是主名**。

### 1.2 主名真实的文字（`name_variant.raw`，NFC 原文）

```sql
SELECT p.country, v.raw, k.norm, k.script
FROM product p
JOIN product_name pn ON pn.product_id=p.product_id
     AND pn.name_type='trade' AND pn.is_primary=1
JOIN name_key k ON k.key_id=pn.key_id
JOIN name_variant v ON v.key_id=k.key_id
WHERE p.country IN ('KR','JP','HK')
GROUP BY p.product_id LIMIT 12;
```

按 **NFC 原始名**逐条判文字（`.tmp/lang1b_probe.py`，369,829 个 key / 各市场主名）：

| 市场 | 产品数 | 有主名 | 主名实际文字（NFC raw） | 备注 |
|---|---:|---:|---|---|
| **KR** | 97,356 | 97,340 | **韩文 97,316 / 汉字 23 / 拉丁 1** | 16 个品目在源里无商品名 |
| **JP** | 12,442 | 12,442 | **纯假名 1,428 / 含汉字 11,014**（含假名合计 **12,191**〔norm 口径；raw 12,193〕；其余 ≈250 个纯汉字） | 无纯拉丁名 |
| **HK** | 13,935 | 13,935 | **拉丁 13,935** | 与源字段一致（§2.3） |

样例（真实 raw，不是构造）：

```
KR-200805356  간포트점안액           → norm 간포트점안액  (script=latin)  ← 典型
KR-198100372  동인당아세피필린정…     → norm 동인당…              (script=latin)
JP-1124001B1039 ユーロジン散1%       → norm ユーロシン散1%              (script=han)
HK-58956      "S.T." NATURAL TEARS… → norm s t natural tears eye     (script=latin)
JP 纯假名样例：ブロモバレリル尿素     → norm フロモハレリル尿素          (script=latin)
```

**站上也不是拉丁**：`site/dist/name/` 里已存在 **52,749 个韩文名字页**（文件名是拆开的 Jamo，如 `1-나잘…html`；`<title>` 显示为韩文「1.나잘스프레이…」）、3,771 个假名名字页（全站名字页 163,379）。本地文字主名**早已发布**。

### 1.3 根因：两处归一化 bug（`etl/normalize_name.py`）

1. **`_script()`（line 97-103）只认 Han / Cyrillic**：Hangul、Kana 都落到 `"latin"` → `name_key.script` 错标。
2. **`_strip_diacritics()`（line 106-109，调用在 line 159）**：对整串做 `NFD` 后只删 combining marks，Hangul 音节被拆成 **Jamo**（Jamo 不是 combining mark，不会被删）且**不重组** → `name_key.norm/key_id/compact` 是 NFD 串。

实测：KR 主名 raw 平均 **14.4 字符**，`norm` 平均 **30.1 字符**（Jamo 拆开约 2 倍）；97,339 个 KR 产品的 key 是 Jamo。

**第三个 bug（让审计看不见）**：`db/consistency_audit_identity.py` 的 `HANGUL_RE = [\uac00-\ud7af]` 只认音节，不认 Jamo → R7「script 与实际字符集不符」对 **10.6 万个韩文 key 完全盲**。本轮 R7 只报 **1,190**：其中 1,184 个是 `latin→kana`（真错标），另 6 个是 `han→kana` 的**口径假阳性**——`normalize()` 会把日文品名尾缀「錠」当剂型词删掉，`norm` 因此只剩假名，而 `script` 是按 raw 判的（han，正确）；R7 用 `norm` 复核才误报。**修 R7 时应按 raw（`key_raw`）判，而不是 `norm`。**

### 1.4 为什么浏览器搜不到韩文（用户可见，P0）

| 路径 | 归一化 | 结果 |
|---|---|---|
| `cli.py` / `lib/search.py` | 两端都走 `normalize_name.normalize()` → **NFD** | `cli.py "간포트점안액"` → **命中 KR-200805356**（exact） |
| 浏览器 / `site/build.py` 客户端 `norm()`（函数名；读取时 line 10051-10055，v1.2.8 改动后约 line 11632） | `NFKC` → **NFC**，只和 `e.k`（= `key_id` = **NFD**）比较 | **no match** |

本地复现（只读预览，未改 dist）：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -m http.server 8765 --directory site/dist
# 浏览器打开：
#   http://127.0.0.1:8765/ko/?q=간포트점안액
#   → 标题「“간포트점안액”에 대한 일치 없음」（no match）
#   http://127.0.0.1:8765/ja/?q=ユーロジン散1%  → 「各国での関連する薬名」（正常）
#   http://127.0.0.1:8765/?q=泰诺                  → 正常
```

计算证据（`.tmp/lang1b_clientnorm.py`）：

```
stored key        : '간포트점안액'   (NFD)
client now (NFKC) : '간포트점안액'                    match= False
client + NFD      : '간포트점안액'   match= True
```

> 结论：LANG1-B 的韩文工作**不是「回源重抓」**，而是「客户端归一化对齐 + 标签回填」；重抓只会得到同样的韩文名。

补充验证（浏览器控制台，只读）：把查询按 `norm(q).normalize('NFD')` 处理后，`shardKeyOf` 返回 `other`、`shardsForQuery` 取到 **`data/idx/shard-other-0.json`（1 片）** —— 说明方案 A 不仅能和 `key_id` 等值，**分片选择也能落到含该 key 的片**；`tier()` 对该 key 返回 `exact`。

---

## 2 市场逐个核对

> `data/sources/` 里只有 MY 等小快照；**KR/JP/HK 的源文件都在 `data/raw/**`（gitignored）**，本节引用路径 + `fetch_meta.json` 的 sha256/行数，换机复核限制见 §7-8。

### 2.1 韩国（KR）

**主名从哪来**：`etl/ingest_kr.py:382` 读 HIRA 약가마스터标准码 CSV 的 **`한글상품명`**；`:741` 把它作为 `trade` 名写入。源文件：`data/raw/kr/20261122/hira_yakga_stdcode_20260831.csv`（55,741,167 B，sha256 `2d006894…`，309,889 行，CP949）；许可与字段已登记在 `docs/许可清单.md` §2.16 / `reports/2026-11-22-kr-license-assessment.md`。

**源里有没有本地文字名字段**：**有，且 100%**。

```
309,889 行中：含韩文 309,888；拉丁-only 1（PANAXGINSENGBALM(PANAXGINSENGBALMRED)，源里本来就是拉丁名）
源里没有英文商品名列（KR 评估报告 line 147：「无英文名（英文名只在 MFDS API 有）」）
```

**入库情况**：97,356 个品目 → 97,340 个有主名（97,316 韩文 / 23 汉字 / 1 拉丁），16 个品目源里没有商品名（如 `KR-200202096`）。`name_variant.raw` 保留 NFC 原文；**KR 独占 106,402 个 `name_key`，其中绝大多数是 Jamo 串**（韩文音节被 NFD 拆开；23 个含汉字、1 个拉丁名除外）。

**许可**：✅ 공공누리 제1유형（KOGL Type 1，须出处、可商用、可演绎）；`source` 行 `hira_kr_medprice` 已在库，`license_url=https://www.kogl.or.kr/info/licenseType1.do`，`data_as_of=2026-08-31`。**本次只是修标签/检索，不新增字段、不新增源 → 不触发重新许可评估。**

**缺口**：① 客户端搜不到（§1.4）；② `script` 标签 106,378 个 key 错；③ 名字页 URL 是 NFD Jamo（页面上显示为 `1.나잘…`，实际文件名是拆开的 Jamo `1-나…`，浏览器会 percent-encode，难看但可用）；④ 16 个无商品名品目；⑤ 源里没有英文名 —— 若产品要求「拉丁对照名」，只能走 MFDS Route A（`data.go.kr 15095677`，许可「이용허락범위 제한 없음」✅，但**账号墙**：无 key 实测 401、注册第 4 步 본인인증，见 §2.16），**不是 v1.2.9 能做的**。

### 2.2 日本（JP）

**主名从哪来**：`etl/markets/jp.py` 的 `COL["name"]=7`（`:110`），读厚労省「薬価基準収載品目リスト」4 个 xlsx 的 **`品名`** 列（`:335` `nfkc(r[COL["name"]])`），`:1092` 归一化后写 `product_name`。源文件：`data/raw/jp_yakka_20261112/tp2026*.xlsx`（7,073 + 3,479 + 1,862 + 28 = 12,442 行）；`成分名` 是日文片假名 INN，用于成分匹配。

**源里有没有本地文字名字段**：**有**。`品名` 全部是日文：12,191/12,442 含假名（norm 口径；raw 12,193），其余 ≈250 个纯汉字，**0 个纯拉丁名**；内用薬文件抽查 7,071 行：含假名 7,023、含汉字 6,131、拉丁-only 0。

**入库情况**：12,442 个主名全部入库。`name_key.script` 现状：11,014 `han`（含汉字的混合名，按「汉字优先」可接受），**1,428 纯假名 product 被标 `latin`**（对应 1,184 个 key + 6 个 `han→kana` = R7 的 1,190）。

**许可**：✅ PDL 1.0（与 CC BY 4.0 兼容、允许商用；须出典 + 标明修改），`docs/许可清单.md` §2.15；`source` 行 `jp_yakka` 已在库。**无新源、无需回源。**

**缺口**：① 1,184 个纯假名 key 的 `script` 标签错（不影响搜索：假名不会被 NFD 分解，客户端 NFKC 能匹配，浏览器已验证）；② 源里没有英文/拉丁商品名（也不该机器翻译，见 §4.1）。

### 2.3 香港（HK）

**主名从哪来**：`etl/ingest_hk_druglist.py:118` 只读 XML 的 **`productName`**；`:189` 的 note 明写「HK DrugList: 無規格/劑型/狀態（English only，DH register）」。源文件：`data/raw/hk_mo/hk_rpp_resource.xml`（4,297,930 B，sha256 `0dacdfc4…`，lastUpdate=`2026-10-23`，14,275 条，入库 13,935）。

**源里有没有本地文字名字段**：**没有**。

- XML 标签全集只有：`drugs / lastUpdate / drug / productName / regCertHolderName / permitNo / activeIngs / activeIng`；**14,275 条 productName 的 CJK 计数 = 0**（`reports/hk-mo-audit.md` §1.2 同结论）。
- data.gov.hk 数据集 `hk-dh-dh_do-hk-dh-do-pharmaceutical-product` 的资源标题（2026-11-17 元数据，CKAN API 现查）是 **“List of Registered Pharmaceutical Products (English Only)”**，`inLanguage: English`，`notes` 只列 name / holder / permit no / active ingredient(s)（2026-11-17 起新增 legal classification，仍无中文名）：
  <https://data.gov.hk/en-data/dataset/hk-dh-dh_do-hk-dh-do-pharmaceutical-product>
- 衞生署藥物辦公室「香港註冊藥劑製品搜尋」页标题本身就是**「（只提供英文版本）」**：
  <https://www.drugoffice.gov.hk/eps/do/tc/consumer/search_drug_database.html>

**结论：现有官方源没有繁中商品名 → 需另找源。** 本轮找到的候选都不满足「开放 + 批量 + 商品级」：

| 候选 | 是什么 | 许可 | 判断 |
|---|---|---|---|
| 醫院管理局 HA Drug Formulary（<https://www.ha.org.hk/hadf/>） | **英文通用名**（不是商品名），如 ABATACEPT / PARACETAMOL | 页脚 **© Hospital Authority. All rights reserved** | 🔴 非商品名、非开放；不作主源 |
| 包装 / 说明书上的中文商品名 | 常见（香港包装常中英并列；未逐条抽样），但无批量、逐条版权 | 各持有人版权 | 🔴 不可批量；人工种子 1.4 万条不现实（且违反「不手工标注」精神） |
| 第三方商业药品库 | 有中文名 | 商业许可 / 不付费（§12） | 🔴 不采用 |
| data.gov.hk 其它数据集 | CKAN `pharmaceutical` 搜索只有这一个数据集；`drug` 13 个结果按标题/notes 抽查未见药品中文名数据集 | — | 无 |

**许可**：现源 `hk_dh` = 🟡 data.gov.hk T&C（免费商用/非商用浏览、下载、分发、复制，须注明来源并承认政府及原机构知识产权），结论见 `docs/许可清单.md` §2.9；**新增源必须先落许可结论再入库**（AGENTS §4「许可先行」），在找到源之前**不写库**。

**产品口径建议**（默认，不需新源）：HK 继续用**英文注册名**，中文侧只给**成分中文名**（`substance.inn_zh`），页面/矩阵明示「HK 注册名单不提供中文商品名」；若产品坚持要繁中品牌名 → 人拍板走 v1.3.x 源评估（HA/包装/合作方）或少量人工种子（逐条出处），**不进 v1.2.9**。

### 2.4 其它市场同病

- **CN / TW**：主名 Han，`script` 正确；CN 126,716 个产品没有 trade 名是**已知商品名回填缺口**（task-85/108，见 `reports/product-name-language-audit.md`），与本地文字无关。
- **SG**：英文注册名（`reports/sg-audit.md`：CJK=0），英文是官方语言，不算缺本地名。
- **MY / NO / CH / FR / ES / MX / CZ / LV**：本地名即拉丁字母，`script=latin` 正确。
- **潜在同类问题**：若未来接入希腊语 / 希伯来语 / 阿拉伯语 / 泰语等市场，`_script()` 同样会返回 `latin`（只认 Han/Cyrillic）——本报告修 `_script()` 时一并加分支，但**已接入市场里只有 KR/JP 受影响**。

---

## 3 许可（只引用现有结论，不重评）

| 市场 / 源 | 许可结论 | 能否再发布 | 义务 | 本次是否新增义务 | 证据 |
|---|---|---|---|---|---|
| KR `hira_kr_medprice` | ✅ 공공누리 제1유형（KOGL Type 1） | 可以（含派生展示） | 署名「건강보험심사평가원 + 공공데이터포털」+ 许可链接 + 基准日；标明已归一化 | **否**（只改标签/检索，不新增字段） | `docs/许可清单.md` §2.16；`reports/2026-11-22-kr-license-assessment.md` |
| JP `jp_yakka` | ✅ PDL 1.0（与 CC BY 4.0 兼容） | 可以 | 出典厚労省 + 标明修改 | **否**（只改标签） | §2.15；`reports/2026-11-13-jp-kr-sources.md` §1 |
| HK `hk_dh` | 🟡 data.gov.hk T&C（免费再使用，须署名） | 现源可以（仅事实字段 + 署名） | 署名數據來源 DATA.GOV.HK / 衞生署藥物辦公室；不发布 XML 原文；不暗示政府背书 | **否**（不新增名字） | §2.9；`reports/hk-mo-audit.md` §1.2 |
| HK 新源（若找到） | 🟡 **未评估** | **未知** | 先落 `docs/许可清单.md` 一行 + `source` 行 + About 署名，再入库 | **是**（许可先行） | AGENTS §4；`docs/许可清单.md` §5 |
| KR Route A（MFDS 15095677，仅当要英文名） | ✅「이용허락범위 제한 없음」 | 可以 | 无强制（本站仍署名） | **是**（新源/新字段），且**账号墙** | §2.16；KR 报告 §2.1 |

> 不重评：NO / CH / MY / EU 等已闭环结论不变。**许可清单有两处口径债**：§2.9 写 HK「页面不启用」、§2.16 标题写 KR「均未接入」，均与现库/现站不符（见 §7 第 6 条）。

---

## 4 实现口径建议

### 4.1 不需要新表 / 新列 / 新名字

- 本地文字名**已经是主名**：`product_name(name_type='trade', is_primary=1)` + `name_variant.raw`（NFC 原文）；`name_key` 是归一化查找键，**不是显示名**。
- 站点显示用 `entry["d"] = displays.get(key_id)` → 取 `name_variant.raw` 第一条；已发布韩文/日文名字页（§1.2）。
- **「主名保留 latin 作对照」对 KR/JP 不成立**：源里没有拉丁商品名（KR 只有韩文，JP 只有日文）；要拉丁对照只能新增源（KR MFDS Route A）或机器翻译（**禁止**：`etl/build_translation_tables.py` 明确品牌名不翻译、AGENTS §9）。HK 反过来：主名是拉丁、缺繁中。
- 因此不要新增 `product_name` 行；新增行会改变 `name_key` / core / 名字页，正是体积与 URL 风险的来源。
- **如果未来 HK 真找到繁中商品名**：正确落法是「英文主名保留 `is_primary=1`」+「繁中名新增 `name_key` + `name_variant` + `product_name(name_type='trade', is_primary=0)`」；它会新增 ≈1.4 万 key / 名字页（§5.2），并且**先过许可**（§3）。KR/JP 不需要这条路——本地名已经是主名。

### 4.2 推荐方案 A（v1.2.9）：修检索 + 回填标签，**零新增名字行**

| 改动 | 文件 / 数据 | 具体 | 风险 |
|---|---|---|---|
| 客户端归一化 | `site/build.py` 客户端 `norm()`（函数名） | 在 NFKC 后、仅当串含 Hangul 音节（`[\uAC00-\uD7AF]`）时追加 `.normalize('NFD')`；或对 `tier()` 比较的 `nq` 统一 NFD（更贴近服务端 `normalize()`） | 改的是**所有查询**共用函数 → 必须跑 CN/EN/JP/KO/ES 回归 + 三语测试 + 首屏守卫；只在 Hangul 分支生效最稳 |
| 标签回填 | `data/drugs.db` `name_key`（**DB 写窗口**） | `UPDATE name_key SET script='hangul' WHERE script='latin' AND norm GLOB '*[ᄀ-ᇿ]*'`（106,378 行）；`script='kana'` 1,184 行；可选 `lang='ko'/'ja'`（schema 已允许 `hangul`/`kana`，无需迁移） | 只改 `script`/`lang`，不改 `key_id/norm/compact` → 不影响检索、core、URL；`check_data` 计数不变 |
| 脚本规则 | `etl/normalize_name.py::_script()`；`db/consistency_audit_identity.py::expected_script()` / `HANGUL_RE` | 加 Hangul（含 Jamo `\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\ud7b0-\ud7ff`）与 Kana 分支（Han 优先，保持现有混合名判定）；**`expected_script` 按 raw（`key_raw`）判，不要按 `norm`**——`norm` 会删掉「錠」等剂型词，产生 6 个假阳性 | 让未来 ingest 与审计不再误标；R7 修好后应为 **0** |
| 测试 | `tests/trilingual/`、`lib/test_search*.py` | 增 KR/JP 本地文字用例（≥3 成分）；断言韩文 exact 命中、JP 假名命中 | 用例应从 DB 取真实名（如 `간포트점안액` / `ユーロジン散1%`），不手写期望 |

**不需要重跑整个国家 ingest**：KR/JP 的名字已在库；回填是 `UPDATE`，不改来源。HK 无源可重跑。

### 4.3 备选方案 B（**不排 v1.2.9**）：键迁移到 NFC

- 做法：`normalize_name` 在 `_strip_diacritics` 后加 `NFC` 重组 → KR 重跑 ingest；把旧 NFD key 的 `name_variant` / `product_name` 引用迁到新 NFC key，删旧 key（否则新增 ≈9.7 万孤儿 key）。
- 收益：core `k` 列 raw **-5.34 MB**（106,402 个 KR 独占 key：9,236,754 → 3,895,992 B；key 列表单独 gzip -0.16 MB）；Jamo URL 消失。
- 代价：`key_file()`（`site/build.py`，函数名）保留非 ASCII 字符 → **≈5.3 万个韩文名字页 URL 会变**（现有 `site/dist/name/` 韩文 Jamo 页 52,749 个）；要 redirect / 保活 / sitemap 变更，SEO 与 R2 成本都不小；还要处理 `u` slug 对 >80 字符 key 的 md5 变化。
- 结论：**v1.3.x 再评估**；v1.2.9 不做。

### 4.4 对 `name_key` 主键 / 检索 / 碰撞的影响

- 方案 A：`key_id` 不变 → 主键、`collision`、`product_name`、`name_variant` 全不动；只修「浏览器能不能搜到」和「标签对不对」。
- 碰撞语义不变（仍按 key 下挂的不同成分数/释放机制推导，不手工标注）。
- 服务端 `lib/search.py` 本来就是 NFD 两端一致，**不需要改**；CLI 已能命中，可作为回归基线。

### 4.5 `db/check_data.py` 与计数口径

- 方案 A：`name_key` **369,829 不变**、`product` 731,078 不变、`name-summary.csv` / `market-summary.csv` / `coverage` 不变；README / About / CHANGELOG 的计数**不用改**。`check_data.py` 只统计 `name_keys` 总数（line 31），不校验 `script`。
- 方案 B：若迁移做对，行数不变但 `key_id` 变；若只重跑不迁移 → `name_key` 多出 ≈9.7 万孤儿行（当前已有 **6,523 个孤儿 key**，见 §7），**禁止**。
- HK 若未来接入新源：产品数不变（13,935），但 `name_key` +≈1.4 万、HK 的 `name_keys`（`market-summary.csv` 现 11,257）≈翻倍、`name-summary.csv` HK trade 行 13,935 → ≈27.9k；`coverage` 不变；README/About/计数口径必须同步（AGENTS §4）。

### 4.6 外部现成方案（AGENTS §12「先找工具」）

- Unicode 规范化用标准库即可：Python `unicodedata.normalize` / JS `String.prototype.normalize`（NFC/NFD），**无新依赖**。
- 不引入 OpenCC（繁简转换，不解决 Hangul/Kana）、不引入 ICU4X（体积大、静态站不需要）。
- 搜索库（FlexSearch / MiniSearch 等）已在 T10 §11 评估为「不采用」；本问题不是索引结构问题，是归一化对齐问题。

---

## 5 体积影响与 T10 结论

### 5.1 基线（现查）

| 项 | 数值 | 占护栏 |
|---|---:|---:|
| `site/dist/data/idx/core.json` raw | **67,963,821 B（67.96 MB）** | **85.0%**（上限 80 MB） |
| 同文件 gzip -9 | **13,321,117 B（13.32 MB）** | **83.3%**（上限 16 MB） |
| core 行数 | 362,502 | — |
| dist | 362,112 文件 / 3,283.1 MiB | — |
| DB `name_key` | 369,829（被 `product_name` 引用 363,306；孤儿 6,523） | — |
| 构建器 `load_index()` 实际入索引 | ≈36.25 万行（只收 trade/inn + 排除复方成分行；与 core 362,502 同量级） | — |
| 首屏 / 首搜 | core **不在**首屏、也不在首搜（T10 §2.4，首屏 365,966 B / 首搜 254,051 B gzip） | 改动不影响 |

> core / dist 数字是 **2026-11-26 构建产物**；DB 是现查（含 v1.2.8 前后变化），下次构建前必须按 §8 重新量。

### 5.2 场景估算（T10 实测的每行成本：CJK 207.8 B raw / 33.7 B gz；latin 180.5 / 40.1；hangul 212.9 / 32.8）

| 场景 | 新增名字行 | core raw 估算 | core gzip 估算 | T10 是否必须 |
|---|---:|---:|---:|---|
| **A：只修检索/标签（本报告推荐）** | **0** | 67.96 MB（85.0%） | 13.32 MB（83.3%） | **不必** |
| A + B 的 NFC 键迁移 | 0（键变短） | **≈62.6 MB（78.3%）** | ≈13.16 MB（82%） | 不必（反而买余量） |
| A + **HK 繁中名**（+13,935） | +1.39 万 | **70.86 MB（88.6%）** | **13.79 MB（86.2%）** | **建议同版做**（>85%，且 +≈1.4 万名字页 / ≈+14k PUT / ≈+100 MB dist） |
| A + **KR 拉丁/英文名**（+97,356，仅 MFDS Route A） | +9.74 万 | **88.19 MB（110.2%）** | **16.60 MB（103.8%）** | **必须先做**（且 +≈9.7 万名字页 / ≈+97k PUT / ≈+0.7 GB dist） |
| A + JP | 0 | 不变 | 不变 | 不必 |

> KR 英文名为**上界**（假设每个英文名都是新 key；与现有拉丁 key 重名会减少行数）。即使只有 50% 唯一（≈4.9 万行）也 ≈78 MB raw（≈97.5%），仍逼近/超过 80；**不要用它来赌护栏**。HK 繁中名同理是上界（同名中文会合并），但量级不变。
>
> T10 的三片方案对这些场景都够：加 HK 后最大片仍是 latin 39.29 MB / 8.73 MB gz；加 KR 英文后 latin ≈56.9 MB raw / ≈12.6 MB gz（71% / 79%），仍低于 80/16。**T10 是「加新名字」的使能项，不是「修检索」的使能项。**

### 5.3 结论（一句话）

**v1.2.9 若按本报告的方案 A 执行（KR/JP 不改数据行、HK 维持英文），不必先做 T10；只有决定「新增 HK 繁中名」或「新增 KR 英文名」时才需要 T10（前者建议、后者必须）。**

---

## 6 工作量与拆单（v1.2.9）

> 前提：Lead 接受 §0 的结论更正（KR/JP 不回源，HK 人拍板）。若坚持「重抓 KR/JP」，请先看 §7——重抓不会改变主名文字，只会制造重复 key。

| ID | 任务 | 工位 | 依赖 | 验收口径 | 需人拍板 |
|---|---|---|---|---|---|
| **L1** | `_script()` / `expected_script()` / `HANGUL_RE` 修 Hangul+Jamo+Kana；DB 窗口回填 106,378 `hangul` + 1,184 `kana`（+可选 `lang`） | backend（唯一 DB 写窗口） | Lead 开写窗口 | `db/consistency_audit_identity.py` R7 **0**（按 raw 判）；`check_data` exit 0；`name_key` 369,829 不变；`script` 分布 KR hangul=106,378 / han=23 / latin=1、JP kana=1,184 | 开写窗口（是） |
| **L2** | 客户端 `norm()` 对 Hangul 做 NFD（或统一 NFD）+ 回归 | frontend（`site/build.py`） | 无 | 本地预览（`SITE_OUT=.tmp/...`）：`/ko/?q=간포트점안액` 命中 KR-200805356；`/ja/?q=ユーロジン散1%`、`?q=泰诺`、英文查询结果与改前一致；首屏 7 指标不回归；A/B ≤500 文件 | 否 |
| **L3** | 三语测试加 KR/JP 本地文字用例；`lib/search` 断言 | backend（`tests/trilingual` + `lib/test_*`） | L1/L2 | `tests/trilingual/run_tests.py` 通过；`unittest lib` 通过；用例从 DB 取真实名 | 否 |
| **L4** | **HK 产品口径决策**：默认「英文注册名 + 中文成分名 + 页面明示」；若要繁中品牌名 → 立项找源/许可评估（v1.3.x） | **Lead / 人** | 本报告 | 写进 `docs/谷段需求队列.md` + `docs/许可清单.md`（若换源）；不先写库 | **是（产品 + 许可）** |
| **L5** | v1.2.9 发布：CHANGELOG → build → CI → A/B → `-DryRun` → `sync_r2.ps1` → `verify_live` → tag/Release | release | L1–L3 + Lead 放行 | build `== done ==`；全量 CI 0 FAIL；verify 0 failures；发布报告写「本次 PUT / 当月累计 / 占比」；core 体积与基线一致 | Lead 放行（发布） |
| **L6** | （可选，v1.3.x）HK 新源扫描 / MFDS Route A 英文名 / NFC 键迁移 | data-scout + backend | L4 决定 | 先许可、后评估；不在 v1.2.9 | 是（许可/账号） |

**顺序**：L1 ∥ L2（互不依赖）→ L3 → L5；L4 可在 L1–L3 期间由 Lead 定，不阻塞。**本版不做**：NFC 键迁移、T10 实施、HK 新源接入、KR 英文名。

---

## 7 失败与缺口（必读）

1. **浏览器韩文检索失败（P0，用户可见）**：`/ko/?q=간포트점안액` → 「일치 없음」；CLI 同查询命中。根因 §1.3/1.4。**不修 = LANG1「语言跟上」在 KR 上不成立**（页面有韩文名但用户搜不到）。
2. **`script` 标签错 107,562 个 key**（按 NFC raw 判：106,378 `latin→hangul` + 1,184 `latin→kana`）。R7 现报 1,190 里另有 6 个 `han→kana` 是 `norm` 口径假阳性（§1.3）；KR 的错标**审计完全看不见**（`HANGUL_RE` 只认音节），所以「R7 = 1,190」不代表只有 1,190 个问题。
3. **`name_key.lang` 全部为 NULL**（369,829 行）——本报告不依赖它，但若后续按语言分组/展示，需要回填（可选）。
4. **名字页 URL 是 NFD Jamo**：`site/dist/name/` 有 52,749 个韩文页，文件名是拆开的 Jamo；浏览器可用但难看，且如果将来迁 NFC 会 **≈5.3 万 URL 变动**（需 redirect/保活）。v1.2.9 不动。
5. **HK 无繁中商品名源**：官方 XML / data.gov.hk 资源 / DH 搜索页三处都明示 English only；HA Formulary 是英文通用名且 © All rights reserved；包装/第三方不满足开放+批量。**这是产品级缺口，不是技术能补的**。
6. **许可清单有两处与现库/现站不一致（口径债）**：① `docs/许可清单.md` §2.9 写 HK「页面不启用」，但 `data/markets.json` 写「已启用（v0.9.0，2026-10-30）」且 `site/dist/data/sources.json` 已含 HK；② 同文件 §2.16 标题仍写 KR「**均未接入**」，但 KR 已于 v1.2.0 入库（`source`/`ingest_run` 均在库）。**需在 v1.2.9 前核对并更正一处**（负责人：Lead/data-scout），否则许可口径与线上不一致。
7. **HK 快照过期**：入库 XML 是 `lastUpdate=2026-10-23`；data.gov.hk 元数据 2026-11-17 已加 `legal classification` 字段（本报告不涉及），下次 HK ingest 应重新取；本轮不抓。
8. **证据可复现性**：KR/JP/HK 的源文件在 `data/raw/**`（gitignored），`data/sources/` 没有对应快照；换机器只能跑 DB SQL / `fetch_meta.json`，不能复核源字段。若 Lead 要求「换机可复核」，需另存小快照/许可说明（本次只读，不做）。
9. **DB 与 dist 不同步**：core 是 2026-11-26 产物；DB 现查 `name_key` 369,829 / 被引用 363,306（比 core 行数多，但 `load_index()` 会过滤）。**下次构建前必须按 §8 重新量 core**，不要直接拿本报告的 67.96/13.32 当下一版基线。
10. **6,523 个孤儿 `name_key`**（只在 `name_variant`，无 `product_name`）：预存在；服务端 `SearchIndex` 会装载它们，极端情况下「名字对上了但没有在售产品」。方案 A 不扩大它；方案 B 若只重跑不清理会更大（§4.5）。
11. **16 个 KR 品目无商品名**（源里 `한글상품명` 空）：无法检索，属源缺口；不要猜。
12. **未验证**：所有浏览器/输入法是否都产出 NFC（标准如此，但未做多端实测）；NFC 迁移后的实际 gzip（本轮只用 key 列表估算，未构建）；HK 若找到源的真实字段/许可（未找到）。
13. **未做**：未写库、未构建、未发布、未抓数据、未改注册表、未 commit；T10 未实施。

---

## 8 复现命令与证据清单

### 8.1 SQL（只读；`db/q.py` 或 `sqlite3 mode=ro`）

```sql
-- ① script 标签分布（Lead 的数字）
SELECT p.country, k.script, COUNT(*) n
FROM product p
JOIN product_name pn ON pn.product_id=p.product_id AND pn.name_type='trade' AND pn.is_primary=1
JOIN name_key k ON k.key_id=pn.key_id
WHERE p.country IN ('KR','HK','JP','CN','TW') GROUP BY 1,2;

-- ② 主名实际文字（raw，按产品去重）+ Jamo
SELECT p.country,
       COUNT(DISTINCT CASE WHEN v.raw GLOB '*[가-힣]*' THEN p.product_id END) hangul,
       COUNT(DISTINCT CASE WHEN v.raw GLOB '*[ぁ-んァ-ヶー]*' THEN p.product_id END) kana,
       COUNT(DISTINCT CASE WHEN v.raw GLOB '*[一-龥]*' THEN p.product_id END) han,
       COUNT(DISTINCT CASE WHEN k.norm GLOB '*[ᄀ-ᇿ]*' THEN p.product_id END) jamo
FROM product p
JOIN product_name pn ON pn.product_id=p.product_id AND pn.name_type='trade' AND pn.is_primary=1
JOIN name_key k ON k.key_id=pn.key_id
JOIN name_variant v ON v.key_id=k.key_id
WHERE p.country IN ('KR','JP','HK') GROUP BY 1;

-- ③ name_key 总量 / 被引用 / 孤儿
SELECT COUNT(*) FROM name_key;
SELECT COUNT(DISTINCT key_id) FROM product_name;
SELECT COUNT(*) FROM name_key WHERE key_id NOT IN (SELECT key_id FROM product_name);
```

### 8.2 脚本（本轮新增，都在 `.tmp/`，不入库）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\lang1b_probe.py       # 各市场主名文字 / script 标签 / 独占 key
& $py .tmp\lang1b_volume.py      # NFC 键节省 + core 场景估算
& $py .tmp\lang1b_clientnorm.py  # 客户端 NFKC vs NFD 与库内 key 的等值验证
& $py db\consistency_audit_identity.py --json .tmp\lang1b-consistency.json   # R7 现状
& $py db\check_data.py
```

### 8.3 浏览器复现（只读预览）

```powershell
& $py -m http.server 8765 --directory site/dist
# /ko/?q=간포트점안액  → 「“간포트점안액”에 대한 일치 없음」（fail）
# /ja/?q=ユーロジン散1% → 正常结果（control）
# /?q=泰诺              → 正常结果（control）
```

### 8.4 源文件 / 页面 / 许可

| 项 | 证据 |
|---|---|
| KR 源 CSV | `data/raw/kr/20261122/hira_yakga_stdcode_20260831.csv`（55,741,167 B，sha256 `2d006894…`，309,889 行，CP949；字段 `한글상품명`）；`data/raw/kr/fetch_meta.json` |
| KR 入库 | `etl/ingest_kr.py:382`（`한글상품명`）、`:741`（trade 名）；`source_id=hira_kr_medprice`，`data_as_of=2026-08-31` |
| JP 源 xlsx | `data/raw/jp_yakka_20261112/tp20261101-01_01.xlsx` 等 4 个（12,442 行）；`fetch_meta.json` |
| JP 入库 | `etl/markets/jp.py:110` `COL["name"]=7`、`:335`、`:1092`；`source_id=jp_yakka`，`data_as_of=2026-11-01` |
| HK 源 XML | `data/raw/hk_mo/hk_rpp_resource.xml`（4,297,930 B，sha256 `0dacdfc4…`，lastUpdate `2026-10-23`，14,275 条，CJK 0） |
| HK 入库 | `etl/ingest_hk_druglist.py:118`（`productName`）、`:189`（English only note）；`source_id=hk_dh`，`data_as_of=2026-10-23` |
| HK 官方英文-only 证据 | data.gov.hk 数据集 <https://data.gov.hk/en-data/dataset/hk-dh-dh_do-hk-dh-do-pharmaceutical-product>（资源标题 “(English Only)”，`inLanguage=English`）；DH 搜索页 <https://www.drugoffice.gov.hk/eps/do/tc/consumer/search_drug_database.html>（「只提供英文版本」） |
| KR / JP / HK 许可 | `docs/许可清单.md` §2.16 / §2.15 / §2.9；`reports/2026-11-22-kr-license-assessment.md`（`한글상품명` 100%、无英文名 line 147）；`reports/2026-11-13-jp-kr-sources.md` §1；`reports/hk-mo-audit.md` §1.2、`reports/hk-ingest-prep.md` line 59/188 |
| 任务前提 | `docs/谷段需求队列.md:33`（`name_key.script` 口径）、`:35`（B 轨「回源」）；`docs/交接-20261127.md:14` |
| T10 | `reports/2026-11-26-t10-index-sharding-design.md` §2.2–2.4、§5；本报告 §5 用其每行成本 |
| 体积基线 | `site/dist/data/idx/core.json`（67,963,821 B）+ T10 实测 gzip 13,321,117 B；`site/dist/data/idx/manifest.json`；`docs/交接-20261127.md:25` |
| 名字页统计 | `site/dist/name/` 163,379 个 HTML；韩文（Jamo）52,749；假名 3,771（`Get-ChildItem` 现查） |

### 8.5 口径说明

- **主名** = `product_name.name_type='trade' AND is_primary=1`；显示取 `name_variant.raw`（NFC）。
- **文字判定** = 对 NFC raw 做正则：Han `[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]`、Kana `[\u3040-\u30ff]`、Hangul `[\uac00-\ud7af]` + Jamo `[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\ud7b0-\ud7ff]`；判定顺序 Han → Kana → Hangul → Latin。
- **`script` 列** = 入库时 `normalize_name.normalize().script` 写的标签，**不是** 显示文字；本报告用 raw 复核。
- **「有源」** = 源字段存在且已入库；**「需另找源」** = 官方源无该字段。
