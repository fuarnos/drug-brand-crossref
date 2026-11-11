# 日本 薬価基準収載品目リスト 取数 + ETL dry-run + ja 接入清单（task-49）

> 日期：2026-11-13（北京时间）· 工位：page-slim · 任务：`task-49`
> 结论先行：日本 **A 类**（厚労省官方 Excel + PDL1.0 开放式许可、无需账号）；4 个 Excel **合计 1,325,527 B / 12,442 品目**；
> `etl/markets/jp.py` 已能 `--fetch` / `--dry-run` / `--self-check`（**无 `--apply`**），在库副本上干跑：
> **预测入库 12,442 产品 / 7,108 组件 / 9,553 新 name_key / 0 新 substance**；
> **规格（NFKC 后）91.4%、剂型派生 83.1%、成分映射 53.3%**。
> **口径红线**：薬価基準 = **医保收载/药价基准**，不是日本上市注册库；页面必须写「日本医保收载品目（薬価基準），不等于该国全部上市药品」。
> 未写 `data/drugs.db`、未改 `site/build.py`、未改 markets/languages 注册表、未 commit / publish。

---

## 0. 交付物与复现命令

| 产物 | 路径 | 说明 |
|---|---|---|
| ETL 骨架 | `etl/markets/jp.py` | `--fetch` / `--prepare-copy` / `--dry-run` / `--self-check`；**没有 `--apply`**；dry-run 拒绝真库 |
| 快照（不入 git） | `data/raw/jp_yakka_20261112/*.xlsx` + `fetch_meta.json` | 4 个官方 Excel + 抓取元数据 |
| 许可证据 | `data/raw/jp_yakka_20261112/license/` | 厚労省条款 HTML/正文、PDL1.0 原文、列表页 HTML/正文 |
| dry-run 结果 | `.tmp/jp-ingest/jp_dry_run.json`、`jp_samples.json` | 库副本 `.tmp/jp-ingest/drugs_jp_copy.db`（只读） |
| 本报告 | `reports/2026-11-13-jp-yakka-acquisition.md` | 许可 / 快照 / 字段 / 比率 / 预测 / 口径风险 / 接入清单 |

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/markets/jp.py --fetch          # 抓 4 个 Excel + 许可证据（可复用缓存）
& $py etl/markets/jp.py --self-check     # 离线断言：许可 / 12,442 / NFKC / 規格 / 剂型 / 映射 / 无 --apply
& $py etl/markets/jp.py --prepare-copy   # data/drugs.db → .tmp/jp-ingest/drugs_jp_copy.db
& $py etl/markets/jp.py --dry-run        # 默认模式；只读库副本，真库拒绝
```

---

## 1. 许可（A 类，证据已存档）

### 1.1 结论

- **数据方**：厚生労働省（MHLW）。
- **站点条款**：厚労省「利用規約・リンク・著作権等」页明写：未特记的内容归厚労省，
  依 **公共データ利用規約（第1.0版）= PDL1.0** 使用。
- **PDL1.0 原文**（デジタル庁）：「どなたでも…複製、公衆送信、翻訳・変形等の翻案等、自由に利用できます。
  **商用利用も可能です**」；「本利用ルールは、クリエイティブ・コモンズ・ライセンスの**表示4.0 国際ライセンス（CC BY）と互換性があります**」；
  且「数値データ、簡単な表・グラフ等は著作権による保護の対象ではありません」。
- **判定：✅ A 类**（可复制/再发布/商用/派生展示；须署名 + 加工标注）。无需账号、无需申请、无 WAF。

### 1.2 条款关键句（逐字）

> 厚労省条款：「当ホームページで公開している情報（以下「コンテンツ」といいます。）は、特記されていない限り
> 厚生労働省に帰属し、権利表記の記載がない限り『**公共データ利用規約（第1.0版）**』（PDL1.0）に準拠した
> 利用条件の下で、利用することができます。」
>
> 义务：「コンテンツを利用する際は**出典を記載**してください。」「編集・加工等して利用する場合は、
> 上記出典とは別に、**編集・加工等を行ったことを記載**してください。また編集・加工した情報を、
> あたかも国（又は府省等）が作成したかのような態様で公表・利用してはいけません。」
>
> 除外：「組織や特定の事業を表すシンボルマーク、ロゴ、キャラクターデザイン」不在许可范围。

**义务落地**：① About/页脚注明「出典：厚生労働省『薬価基準収載品目リスト』+ 页面 URL」；
② 因为本站会做 NFKC/剂型派生/成分映射等加工，必须写「（厚生労働省データ）を加工して作成」；
③ 不用厚労省 logo；④ 不暗示政府背书。

### 1.3 证据文件（`data/raw/jp_yakka_20261112/license/`）

| 文件 | 字节 | 内容 |
|---|---|---|
| `mhlw_chosakuken.html` / `.txt` | 51,555 / 12,595 | 厚労省「利用規約・リンク・著作権等」原文 + 纯文本 |
| `mhlw_terms_pdl.txt` | 2,219 | PDL1.0 适用段 + 出典/加工义务摘录 |
| `pdl_1.0.html` / `.txt` | 59,078 / 10,582 | デジタル庁 PDL1.0 全文（含 CC BY 兼容、商用可、数值数据不受版权保护） |
| `yakka_list_page.html` / `.txt` | 23,234 / 13,318 | 薬価基準収載品目リスト页面原文（Shift_JIS，已解码存 UTF-8 文本） |

`fetch_meta.json` 记录 4 个 Excel 的 URL / HTTP 头 / 字节 / sha256 / 抓取时间；`--self-check` 会核对许可 id 与证据文件存在。

### 1.4 `docs/许可清单.md` 建议行（本工位写权限不含 docs，未改；Lead 统一提交）

```md
| `jp_yakka` | 厚生労働省「薬価基準収載品目リスト」4 个官方 Excel（内用薬 7,073 / 注射薬 3,479 / 外用薬 1,862 / 歯科用薬剤 28 = **12,442 品目**；2026-11-01 適用版；日文全角原文） | ✅ **A 类：公共データ利用規約（第1.0版）PDL1.0**（厚労省站点条款明示；PDL1.0 与 CC BY 4.0 兼容、明许可商用） | 可以（含派生展示） | 出典：厚生労働省 + 页面 URL；加工后注明「加工して作成」；不得让人误以为政府作成；不用 logo | 中（医保收载 ≠ 上市注册；无 ATC；剂型需派生） | ❌ 未接入（ja 语言随行，v0.11.x 计划） | https://www.mhlw.go.jp/topics/2026/04/tp20260401-01.html ；https://www.mhlw.go.jp/chosakuken/index.html ；https://www.digital.go.jp/resources/open_data/public_data_license_v1.0 |
```

---

## 2. 数据快照（`data/raw/jp_yakka_20261112/`，不入 git）

列表页：`https://www.mhlw.go.jp/topics/2026/04/tp20260401-01.html`（「令和8年11月1日適用」）。

| key | 文件 | 区分 | 字节 | 行（品目） | sha256（前 16） | Last-Modified |
|---|---|---|---:|---:|---|---|
| naisho | `tp20261101-01_01.xlsx` | 内用薬 | 726,965 | 7,073 | `b5891578c2289084…` | 2026-10-30 01:21 UTC |
| chusha | `tp20261101-01_02.xlsx` | 注射薬 | 358,163 | 3,479 | `198dac81e6141f9a…` | 2026-10-30 01:21 UTC |
| gaiyo | `tp20261014-01_03.xlsx` | 外用薬 | 215,907 | 1,862 | `91b30234eafc4fa6…` | 2026-10-13 01:11 UTC |
| shika | `tp20260401-01_04.xlsx` | 歯科用薬剤 | 24,492 | 28 | `1f523b83fd121cec…` | 2026-03-05 01:02 UTC |

**合计 1,325,527 B / 12,442 品目**（与 phaseb-plan 实测一致）。HTTP 200、`Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`，
有 `ETag`；**4 个文件的「現在品目を反映」日期不同**（内用/注射 11-01、外用 10-14、歯科 04-01），
页面口径统一用 **2026-11-01 適用版**，但报告/About 要注明各表反映日期不一。

每个 Excel：单 sheet `ＨＰ用`、**15 列**（表头 1 行）、**全角日文**、无合并单元格干扰（read_only 读 12,442 行全部有 `薬価基準収載医薬品コード`）。

---

## 3. 字段与口径

| 列 | 字段 | 用途 / 注意 |
|---:|---|---|
| 0 | 区分 | 内用薬 / 注射薬 / 外用薬 / 歯科用薬剤 → **只到给药大类**，不是剂型 |
| 1 | 薬価基準収載医薬品コード | 12,442 个唯一 → 产品 id `JP-<code>` |
| 2 | 成分名 | 日文一般名（片假名 + 盐名，如 `ドネペジル塩酸塩`）；复方用 `・` 分隔 |
| 3 | 規格 | `10mg1錠` / `5%500mL1袋` / `1錠` / `10cm×14cm1枚` → NFKC 后解析 |
| 4–6 | （空列） | 不含数据 |
| 7 | 品名 | **商品名**（含规格/剂型/厂家标注，如 `ユーロジン1mg錠`、`○○「トーワ」`） |
| 8 | メーカー名 | 厂家；**1,591 行空**（多为「成分名 = 品名」的通用名品目） |
| 9 | 後発医薬品加算対象 | `後発品` 等 → `is_branded=0` |
| 10 | 先発医薬品 | `先発品` → `is_branded=1` |
| 11 | 同一剤形・規格の後発がある先発 | 只作事实，不用于替代推荐 |
| 12 | 薬価 | **日元药价**（每 1 錠/1 管 等），12,442 行全部有数值；只展示，不换算 |
| 13 | 経過措置による使用期限 | 非空 **413 行**（过渡期品目）→ `status='discontinued'`（不是「已撤市」的等价说法） |
| 14 | 備考 | 少量备注 |

> 「薬価」是价格事实，不是剂量；本站**不做价格换算、不做剂量换算、不判断可互换**（§1 三条底线）。

---

## 4. ETL（`etl/markets/jp.py`）

- **CLI**：`--fetch` / `--prepare-copy` / `--dry-run`（默认）/ `--self-check`；**没有 `--apply` / `--rollback`**
  （ja 语言与 JP 市场未接入；`self-check` 断言 `--apply` 被拒、默认库是 `.tmp` 副本）。
- **库纪律**：dry-run 显式拒绝 `data/drugs.db`；默认打开 `.tmp/jp-ingest/drugs_jp_copy.db`（`mode=ro`）。
  本次运行前后真库未变：428,703,744 B / mtime `2026-11-11 10:33:14` / sha256 `d6e4d088…`。
- **NFKC**：所有单元格先 `unicodedata.normalize("NFKC", …)`（`１ｍｇ１錠`→`1mg1錠`、`Ｔ’ｓ製薬`→`T's製薬`），
  另把全角/弯引号、全角横线归一；**这是规格解析的前提**（不做 NFKC 规格抽取率会接近 0）。
- **复用**：`normalize_name.normalize()`（名称侧）、`ingest_ema_medicines._variant_resolver()`（variant）；
  剂型/规格/成分解析为本市场新增（无独立剂型列、无 ATC、日文一般名）。
- **日文成分映射**：`成分名` →（剥离盐名 `塩酸塩/ナトリウム/ベシル酸塩/水和物…`）→ 片假名转罗马字 →
  音韵辅音骨架（含 c/s、t/s、l/r、b/v、d/z/j 等价类）→ 对库内 `substance.inn_en` **唯一命中**才接受；
  多候选时仅当「基名是其余候选的前缀」才取基名（如 Donepezil / Donepezil Hydrochloride）；
  只对 `inn_en` 含拉丁字母的 substance 做匹配（库内有一部分 `inn_en` 是中文主名，不能参与音韵匹配）。
  另加 6 条汉字成分名词典（ブドウ糖/生理食塩液/精製水 等）。**不新增 substance、不做模糊编辑距离**。

---

## 5. dry-run 结果（`.tmp/jp-ingest/jp_dry_run.json`）

### 5.1 体量

| 指标 | 数值 |
|---|---|
| 品目（行） | **12,442**（コード唯一 12,442，重复 0） |
| 区分 | 内用薬 7,073 · 注射薬 3,479 · 外用薬 1,862 · 歯科用薬剤 28 |
| 唯一品名 / 唯一成分名 | 11,845 / 2,709 |
| 厂家 | 316 个（10,851 行有厂家，1,591 行空） |
| 同品名多规格 | 289 个品名 |
| 价格 | 12,442 行全部有 `薬価`（日元） |

### 5.2 规格（NFKC 后）

| 指标 | 数值 |
|---|---|
| 解析出数值剂量 | **11,378 / 12,442 = 91.4%** |
| 含每包装分母（`100mg5mL1瓶`） | 3,092 |
| 仅尺寸（`10cm×14cm1枚`） | 86（不当剂量） |
| 单位 top | mg 6,409 · % 1,895 · g 1,740 · mL 734 · unit 236 · L 186 · IU 115 |
| 包装单位 top | 錠 4,376 · 瓶 1,515 · 管 763 · カプセル 551 · 筒 518 · 袋 514 |
| component 带剂量 | **6,227 / 7,108 = 87.6%** |

> `1錠` / `1瓶` / `1回分` 这类只有包装数量的规格**不当剂量**（留空）；`10cm×14cm` 归为尺寸。

### 5.3 剂型派生（无独立剂型列）

| 指标 | 数值 |
|---|---|
| **品名尾缀/包含词派生** | **10,337 / 12,442 = 83.1%** |
| **`区分` 兜底** | **2,105 / 12,442 = 16.9%**（注射薬→injection，其余→other） |
| form_base 分布 | tablet 4,375 · injection 3,495 · **other 1,688** · powder 1,067 · capsule 564 · topical 461 · ophthalmic 295 · transdermal 180 · inhalation 89 · liquid 85 · suppository 62 · nasal 60 · rectal 21 |

> 兜底 `other` 1,688 是主要缺口（多为内用/外用的散剂、透析液、造影剂、生物制品、卫生材料等）；
> 页面要标「剂型由品名派生（83.1%），其余按区分兜底」。

### 5.4 成分映射（日文一般名 → INN）

| 指标 | 数值 |
|---|---|
| token 总数 | 13,342（单成分 11,678 品目、复方 764 品目） |
| **映射成功** | **7,108 / 13,342 = 53.3%** |
| 方法 | katakana-skeleton 5,523 · skeleton-equiv 1,391 · jp-kanji-dict 194 · **ambiguous 814**（不猜） · unmapped 5,420 |
| 唯一未映射写法 | 1,279 种 |
| 产品级 | 全部成分映射 6,455 · 部分映射 363 · 一个都没映射 5,624 |
| 映射到的 substance | **1,045 个**（全库 12,637）；**JP 独占（库内无产品）1 个** |

- 主要缺口（合法缺口）：**溶液/透析液类**（腹膜透析液 132、人工透析液 43、維持液 35）、**复方/生物制品/造影剂**、
  日文习惯名与 INN 音韵差异大的（ヒドロクロロチアジド、クロルヘキシジングルコン酸塩、フルチカゾン…）。
- 与既有市场的关系：不是「日本新增成分」，而是**同一 INN 的第 11 个市场**；按 substance 与既有 10 国
  共享（AU 702 / CA 790 / CN 539 / ES 771 / EU 488 / GB 818 / HK 633 / MX 596 / SG 534 / TW 732 / US 784 个成分可对上）。
- **无 ATC**：成分页 ATC 只能沿用库内 `substance.atc`，不新增。

### 5.5 状态 / 先発後発

| 指标 | 数值 |
|---|---|
| active（収载、无経過措置） | **12,029** |
| discontinued（`経過措置による使用期限` 非空） | **413** |
| 先発品 / 後発加算対象 / 未标注 | 4,238 / 4,455 / 3,749 |
| `is_branded=1` | 7,987 |

> 口径：**薬価基準収載 = 收载（全部 12,442 行）**；`経過措置` 是过渡期（到期后退出），记 `discontinued`。
> 「収載 ≠ 当前在售」必须在页面写清——**这不是上市注册库**。

---

## 6. 预测入库条数（仅预测，本脚本无写库路径）

| 表 | 预测 | 说明 |
|---|---:|---|
| `product` | **12,442** | 一行 = 一个 `薬価基準収載医薬品コード`（`JP-<code>`）；`country='JP'`、`region=NULL` |
| `product_component` | **7,108** | 只写成分全部映射上的产品；带剂量 6,227；无 variant 0 |
| `product_name` | **12,442** | `name_type='trade'`（品名 = 商品名，含厂家标注） |
| `name_key` | 新建 **9,553** / 唯一名 9,555 | 名字页预估见 §8.6 |
| `name_variant` | 新建 **11,843** | `source_id='jp_yakka'` |
| `substance` | **0 新增** | 映射不上一律空着（1,279 种写法缺口） |
| `source` / `ingest_run` | 各 1 行 | `jp_yakka`（license / license_url / retrieved_at / data_as_of=2026-11-01） |
| 药价 / 先発後発 / 経過措置 | 只作字段 | `price` 进 `product.note` 或页面事实字段（schema 无 price 列，需另议） |

### 6.1 回滚清单草案（写库窗口用，本次未执行）

1. **写前备份**：`Copy-Item data/drugs.db data/backups/drugs-pre-jp-<YYYYMMDD>.db`，记录 sha256 + 四表计数。
2. **manifest**：`.tmp/jp-ingest/jp_manifest_<run_id>.json` 含 `product_ids=12,442`、`name_variant_ids`、
   `name_key_ids_created`、`source_id`、`run_id`、`applied_at`。
3. **撤销顺序**（单事务）：`DELETE FROM product WHERE country='JP' AND source_id='jp_yakka'`
   （级联 `product_component` / `product_name`）→ `DELETE FROM name_variant WHERE source_id='jp_yakka'`
   → 只删 manifest 里且无任何引用的 `name_key` → `DELETE FROM source` / `ingest_run`。
4. **验证**：四表计数回到备份值；`PRAGMA foreign_key_check` 空；`PRAGMA integrity_check` = ok；
   `db/check_data.py` 通过；`coverage` 无 JP 行。
5. **schema 回滚**：`product.country` CHECK 加 `JP` 需要重建表（`db/init_db.py` 迁移只前进）；
   回滚以备份恢复为稳妥做法。

---

## 7. 口径红线与风险

| # | 风险 / 未决 | 影响 | 处置 |
|---|---|---|---|
| 1 | **薬価基準 ≠ 上市注册库**（未收载的自费/自由诊疗/OTC 药不在内） | 页面若写「日本上市药品」= 错误口径 | 页面固定文案：「日本医保收载品目（薬価基準），不等于该国全部上市药品；収載 ≠ 当前在售」 |
| 2 | 4 个 Excel 反映日期不同（11-01 / 10-14 / 04-01） | 「数据截止日」不统一 | About 写「2026-11-01 適用版（各表反映日期不同）」 |
| 3 | **无 ATC、无独立剂型列、无给药途径列** | 不能做 ATC 归类/途径筛选 | 不造 ATC；剂型派生 83.1% 并标注；route 留空 |
| 4 | 成分映射 **53.3%**（1,279 种写法未映射） | 5,624 个品目无 component（名称层） | 页面标「成分未收录（名称层）」；缺口清单入报告，后续补日文一般名对照（人工/WHO INN 日文名） |
| 5 | 剂型 `other` 1,688 | 成分页/筛选少标签 | 补词表（透析液/造影剂/生物制品/卫生材料）；先如实标 other |
| 6 | 1,591 行无厂家 | 明细「品牌」列可能空 | 显示「厂家未收录」，不猜 |
| 7 | 289 个品名多规格 / 复方 764 品目 | 同名候选集 | 商品名不是主键：按 `(JP × 剂型 × 规格 × 成分)` 出候选集（§1.1） |
| 8 | 薬価（日元）只展示 | 不能换算/比价 | 只作价格事实；不做剂量/货币换算，不给用药建议 |
| 9 | 平行进口/生物制品/疫苗在收载表里 | 不能与注册库口径混用 | 页面只写「收载品目」，不推断上市状态 |
| 10 | 日文一般名→INN 是音韵近似 | 存在错配风险（已用唯一候选 + 基名规则约束） | 写库前人工抽检 ≥30 条；错配即回退为未映射 |

---

## 8. 站点接入清单（只写方案，本轮不改 `site/`）

现状基线（`site/dist` 实测）：**121,450 文件 / 920,332,551 B（920.3 MB）/ 121,239 HTML**；
name 77,147 页（均 4,147 B）· drug 12,431（10,466 B）· maker 15,213（9,062 B）· combo 15,248（5,216 B）；
sitemap 63,685 URL；`data/idx/core.json` **42.8 MB raw / 9.95 MB gzip**（发布护栏 gzip 2.5–12 MB，余量 ≈2.05 MB）。

### 8.1 `data/markets.json`（加 JP，先 `enabled:false`）

```json
{
  "code": "JP", "kind": "country", "parent": null, "group": "ASIA",
  "name": {"en": "Japan", "es": "Japón", "zh": "日本"},
  "i18n_key": "home.jp", "flag": "🇯🇵",
  "source_id": "jp_yakka", "extra_source_ids": [],
  "default_lang": "ja", "languages": ["ja"],
  "enabled": false, "order": 86, "data_as_of": "2026-11-01",
  "notes": "厚生労働省「薬価基準収載品目リスト」（PDL1.0）：12,442 个医保收载品目；**不是上市注册库**，収載≠在售；无 ATC、剂型由品名派生（83.1%）、成分映射 53.3%。页面必须写「日本医保收载品目（薬価基準），不等于该国全部上市药品」+「出典：厚生労働省…を加工して作成」。"
}
```
- `order` 建议 86（SG 85 与 HK 88 之间）；`parent=null`（日本不是 EU 成员国）。
- 校验：`& $py lib/markets.py --check`（要 DB `source` 先有 `jp_yakka` 行）、`tests.test_markets_registry`。

### 8.2 `data/languages.json`（**新增 ja，当前没有 ja**）

```json
{
  "code": "ja",
  "name": {"en": "Japanese", "es": "Japonés", "zh": "日语"},
  "native_name": "日本語", "ui_label": "JA",
  "script": "japanese", "dir": "ltr", "hreflang": "ja",
  "path": "ja/", "i18n_key_prefix": "ja",
  "default_country": "JP", "region": null,
  "enabled": false, "order": 45,
  "notes": "日本語 UI。/ja/ 路由 + hreflang=ja；数据语言=日文原文（品名/成分名/規格）。"
}
```
`lib/markets.py` 的 `ALLOWED_SCRIPTS` 已含 `japanese`（无需改校验器）。

### 8.3 I18N ja 键集：**约 596 条**（工作量写清）

- 主字典 `I18N`：en/es/zh 各 **237 键**；页面级字典另有 `PAGE_I18N`(27)、`COVERAGE_I18N`(25)、
  `WARN_I18N`(54)、`COMBO_I18N`(18)、`MAKER_I18N`(31)、`META_I18N`(15)、`GLOSSARY_I18N`(13)、
  `ABOUT_I18N`(19)、`WHATS_I18N`(20) 等，**合计 ≈596 条/语言**。
- ja 建议照 es/zh **直接写在 `site/build.py` 的每个 I18N 字典里**（键集与 en 完全一致）；
  `zh-Hant` 的 JSON 覆盖机制不适用于 ja。
- 额外要翻译：`coverage.gap.jp`（医保收载口径）、About 署名段、404/what's-new/术语表长文；
  `whatsnew.lang_note` 的「机翻」声明同样适用 ja。
- 校验：`& $py deploy/i18n_check.py`（四语键集规则会在加 ja 后扩展为五语，需同步 `LANGS`）。

### 8.4 路由 / SEO / 站点结构

1. `site/build.py:LANGS` 加 `("ja", "JA", "ja/")`；`/ja/` 入口 7 页（同 es/zh 结构）；`<html lang="ja">`。
2. hreflang：每页多 1 个 `ja` alternate + `x-default` 仍指 en；`?lang=ja` 深链与 localStorage 一致。
3. 硬编码国家顺序：`COUNTRY_PRIORITY`（`site/build.py`）加 `"JP"`；`U2_COUNTRIES` 按需加 JP；
   国家下拉/矩阵列序由 `window.COUNTRY_ORDER` 生成（已注册表化）。
4. **名字页体积守卫**：`SINGLE_NAME_PAGE_MARKETS = {CN, TW, ES, MX}`；JP 默认**不进** →
   只给「≥2 产品」或「无成分」的名字键建页 = **5,695 个新名字页**；若加 JP → **9,555 页**（+≈16 MB）。
   **建议先不加**，上线后看体积再定。
5. 覆盖页：`coverage` 视图自动多一行 JP；`coverage.gap.jp` 文案（五语）：
   「日本医保收载品目（薬価基準）12,442 个；**不等于该国全部上市药品**；収載≠在售；无 ATC；
   剂型由品名派生（83.1%，其余按区分兜底）；规格来自規格列（91.4%）；成分映射 53.3%；価格为日元薬価。」
6. About：署名「出典：厚生労働省『薬価基準収載品目リスト』（页面 URL），PDL1.0，**を加工して作成**」
   + PDL1.0 链接 + 数据日期 2026-11-01；`source.license_url` 指向厚労省条款页。

### 8.5 测试与验收（站点窗口）

```powershell
& $py lib/markets.py --check
& $py -m unittest tests.test_markets_registry -v
& $py -m unittest discover -s etl -t etl          # 建议加 etl/markets/test_jp.py（固定小样本，不联网）
& $py tests/trilingual/run_tests.py               # 加 ja 样本：ロキソニン→loxoprofen、ムコダイン→carbocisteine…
& $py site/build.py                               # == done ==（串行 owner）
& $py deploy/first_screen_check.py                # 改前/改后各一次
& $py deploy/ci_checks.py
```
人工抽检：`/ja/` 200 + hreflang；覆盖页 JP 行带「医保收载」限定；3 条日文检索（商品名/一般名）；
sitemap 含 JP 名字页；链接/404 抽检；页数/索引大小/首屏体积回归。

### 8.6 体积预估（相对当前 dist 920.3 MB）

| 项 | 增量 | 依据 |
|---|---|---|
| 名字页 | **+5,695 页 ≈ +23.6 MB**（JP 进守卫则 +9,555 页 ≈ +39.6 MB） | 名字页均 4,147 B |
| 成分页（drug/） | **+1 页**（JP 独占 1 个 substance）≈ +10 KB；1,045 个已有成分页加 JP 行 | 成分页均 10,466 B |
| 厂家页 | +约 150–250 页 ≈ +1.4–2.3 MB | 316 个厂家（多数日本本地） |
| 组合页 | +70 页 ≈ +0.37 MB | 复方组合 70 种；组合页均 5,216 B |
| 覆盖页/About/`/ja/` 入口 | ≈ +0.4 MB | 覆盖 +1 行、`/ja/` 7 页 |
| **第 6 种 UI 语言（ja）的 hreflang/切换器** | **+12–15 MB**（12 万页各 +100–120 B） | 当前已有 5 语（en/es/zh/zh-Hant/fr 前） |
| `core.json` | raw +≈2.0 MB（→44.8 MB）/ **gzip +≈0.45 MB（→10.4 MB）** | 9,553 新名字键；**护栏 12 MB，余量 ≈1.6 MB** |
| sitemap | +5,695 条（→69,380）≈ +0.7 MB | — |
| **合计** | **≈ +40 MB（+4.3%）→ ≈ 960 MB**；JP 进单包装守卫 ≈ +56 MB（→976 MB） | — |

---

## 9. 复现与可复核

```powershell
& $py etl/markets/jp.py --self-check      # 全部通过（0 失败）
& $py etl/markets/jp.py --dry-run         # 控制台摘要 = .tmp/jp-ingest/jp_dry_run.json
& $py db/q.py "SELECT COUNT(*) FROM product WHERE country='JP'"   # 0（真库未写）
Get-FileHash data/raw/jp_yakka_20261112/*.xlsx -Algorithm SHA256   # 与 §2 对照
```
关键数字均来自 `.tmp/jp-ingest/jp_dry_run.json`（`rows` / `dosage_form` / `strength` / `substance` /
`status` / `flags` / `inn_overlap` / `would_write`）与 `fetch_meta.json`。

---

## 10. 未做 / 待定

- **没有 `--apply`**（站点 ja 未接入）；写库窗口需先做 `product.country` CHECK 加 `JP` 的 schema 迁移。
- **没有人工校对的日文一般名→INN 对照表**：当前是音韵近似（唯一候选 + 基名规则），53.3% 映射率；
  若要提高覆盖率，需要一份可再发布的日文 INN 名称表（PMDA/日本薬局方）或人工校对 ≥1,000 条。
- **没有 ATC / 给药途径 / 独立剂型**：数据源本身没有，页面口径必须写清。
- **药价字段**：schema 无 price 列；写库窗口需决定放 `product.note` 还是新增列（另开 schema 任务）。
- 4 个 Excel 反映日期不同，About 要写「2026-11-01 適用版（各表反映日期不同）」。

_本报告为取数与干跑产物，不含任何写库、建站或发布动作。_
