# 繁体中文（zh-Hant，台湾用语优先）文案字典（task-53）

> 日期：2026-10-28 ｜ 数据：`site/build.py` 的 I18N `zh`（BASE + ABOUT/PAGE/WARN 合并后）
> 产物：`data/i18n_zh_hant.json`（203 键）· 本报告 · `.tmp/zh-hant/`（词典、生成脚本、校验明细）
> 边界：**未改 `site/build.py`、未写 `data/drugs.db`、未跑 git/发布**；本任务只产数据与接入建议。

---

## 1. 结论

| 指标 | 结果 |
|---|---:|
| 源键数（I18N zh，当前 build.py） | **203**（任务预估 ~191；build.py 在 v0.5.2 后新增 `combo.*` / `maker.*` / `same.*` / `res.partial` 等键） |
| 输出键数（zh-Hant） | **203** |
| 键集合一致 | ✅ 无缺键、无多键 |
| 实际有改动的键 | **180**（23 键繁简同形：成分、品牌、西班牙、已停售、警示→警語 等） |
| 空值 | **0** |
| 占位符（`@@X@@` / `{name}`）一致性 | **0 不一致**（13 个含占位符的键全部保留） |
| HTML 标签结构一致性 | **0 不一致**（20 个含 HTML 的键，标签序列完全相同） |
| ASCII/代码标识一致性 | **0 不一致**（路径、命令、`documented` 等原样） |
| **残留简体字抽样检测** | **0 个键**（149 个简体字已按表转换，无简体残留） |
| 字符量 | 6,738 → 6,743（+0.07%，繁简同形字多） |
| 数据文件 | `data/i18n_zh_hant.json` 20 KB（其中 zh-Hant 字典 JSON 约 18.1 KB raw / ~5–6 KB gzip） |

一句话：**203 键已全部转为繁体、台湾用语优先，自动校验全部通过（键数/空值/占位符/HTML/ASCII/残留简体 6 类 0 问题）；专有名词、INN 中文名、许可法律表述仍需人工复核。**

---

## 2. 转换规则（可复现，非无脑字符替换）

### 2.1 词典与来源

| 词典 | 用途 | 来源/许可 |
|---|---|---|
| `STPhrases.txt`（49,270 条） | 简体短语→繁体 | OpenCC，Apache-2.0 |
| `TWPhrases.txt`（851 条） | 大陆用语→台湾用语（字段→欄位、查看→檢視、文件→檔案…） | OpenCC，Apache-2.0 |
| `STCharacters.txt`（4,029 条） | 逐字简→繁 | OpenCC，Apache-2.0 |
| `TWVariants.txt` + `TWVariantsPhrases.txt` | 台湾字形（裏→裡、爲→為、覈→核…） | OpenCC，Apache-2.0 |
| `TSCharacters.txt` | 把 TWPhrases 的繁体源词展开成简体写法，便于在简体原文上命中 | OpenCC，Apache-2.0 |
| **`TW_TERMS`（自建，112 条）** | OpenCC 未覆盖的台湾 IT/药事术语 + 断词保护 | 本项目自建（脚本内可审计） |

> OpenCC 词典已缓存在 `.tmp/zh-hant/`（生成脚本 `fetch_opencc.py` 可重下）；许可为 Apache-2.0，已写入 `data/i18n_zh_hant.json` 的 `_meta.license_note`。

### 2.2 转换算法（单次扫描，避免 OpenCC 经典二次转换 bug）

`convert()` 对每个汉字位置按以下优先级做**单次扫描**：

1. `TW_TERMS`（自建台湾术语，长词优先，含断词保护 identity 条目）；
2. `TWPhrases`（官方台湾用语，已用 `TSCharacters` 展开简体源）；
3. `STPhrases`（简→繁短语）；
4. `TWVariantsPhrases`；
5. 未命中 → 逐字 `STCharacters`（取 OpenCC 首选字）；
6. 全文最后再跑 `TWVariants`（台湾字形）+ `TW_TERMS` 兜底（短语表产出的大陆词如「數據」→「資料」）。

**关键修正**（首版两次全局替换会踩的坑，已修复并在校验里回归）：
- `名表` 被 OpenCC 当成「手表」→「名錶」：加 `商品名表` identity 保护，输出正确为「商品名表」；
- `西里尔字母` 被短语表正确转成「西里爾」后，逐字表又把「里」转成「裡」：单次扫描后不再二次转换，输出「西里爾」；
- `存储` 被逐字转成「存儲」（词序错误）：自建表映射「儲存」；
- `里人工維護`（应在“文件裡”）：断词保护 → 「裡人工維護」。

### 2.3 保留不译（by design）

站名 `Medicine Brand Cross-Reference`、INN/英文药名、监管机构英文名（FDA/EMA/MHRA/Health Canada DPD/AEMPS CIMA/PBS/TGA/NMPA…）、法规条款引用、代码标识（`documented`、`data/seed_nicknames.py`、命令）、URL、占位符 `@@X@@`/`{name}`——全部原样保留（校验第 3/4/6 项已断言）。

---

## 3. 术语差异（台湾优先）

### 3.1 自建 TW_TERMS 实际命中（64 对，219 次；仅列有意义的改写）

| 大陆写法 | 台湾写法 | 命中 | 示例键 |
|---|---|---:|---|
| 数据 / 数据源 | 資料 / 資料來源 | 9 | `report.issue_title`、`about.sources` |
| 搜索 / 搜索框 | 搜尋 / 搜尋框 | 3+1 | `home.hint_idle`、`ac.suggestions` |
| 用户 | 使用者 | 2 | `nick.unverified`、`about.nick` |
| 界面 | 介面 | 1 | `whatsnew.lang_note` |
| 文件 | 檔案 | 2 | `error.local_file`、`about.sources` |
| 网络 | 網路 | 2 | `nick.slang`、`about.nick` |
| 支持 | 支援 | 1 | `home.sub` |
| 加载 | 載入 | 6 | `home.loading`、`res.partial` |
| 缓存 | 快取 | 1 | `home.hint_idle` |
| 页面 / 页面不存在 | 頁面 / 找不到頁面 | 6+1 | `notfound.title`、`report.field_page` |
| 链接 | 連結 | 4 | `notfound.p1`、`warn.source_note` |
| 厂家 | 廠商 | 3 | `col.mah`、`maker.title` |
| 药物 / 药品 | 藥物 / 藥品 | 3+3 | `conf.title`、`about.terms` |
| 剂量 / 剂型 / 规格 | 劑量 / 劑型 / 規格 | 6+3+4 | `col.dose`、`name.form`、`drug.strength` |
| 盐型 / 缓释 / 释放 | 鹽型 / 緩釋 / 釋放 | 1+1+4 | `warn.intro`、`name.warning` |
| 许可 / 发布 / 来源 | 許可 / 發布 / 來源 | 12+4+12 | `warn.source_note`、`about.sources` |
| 警示 | **警語** | 8 | `nav.warn`、`warn.title`、`warn.drug_summary` |
| 在售 / 已撤市 | **販售中 / 已下市** | 1+1 | `drug.status.active`、`drug.status.withdrawn` |
| 日志 | 日誌 | 3 | `nav.whatsnew`、`whatsnew.title` |

### 3.2 OpenCC 官方台湾用语命中（TWP，14 对）

`字段→欄位`(5)、`查看→檢視`(3)、`社区→社區`(3)、`文件→檔案`(2)、`视图→檢視`(2)、`全角→全形`(1)、`打开→開啟`(1)、`前缀→字首`(1)、`实时→即時`(1)、`声明→宣告`(1)、`代码→程式碼`(1)、**`对乙酰氨基酚→對乙醯胺基酚`(1)**（台湾药名优先）。

### 3.3 台湾字形（TWVariants，5 类）

`裏→裡`(10)、`覈→核`(10)、`爲→為`(5)、`纔→才`(1)、`麼` 保留(4)。

### 3.4 简体字逐字转换

149 个不同简体字、609 次（药→藥 23、个→個 22、条→條 22、对→對 22、产→產 22、国→國 21、与→與 21、单→單 18、没→沒 17、页→頁 11…）。

---

## 4. 校验结果（`validation.json`，可复跑）

| 校验项 | 方法 | 结果 |
|---|---|---|
| 键数/键集合 | `set(zh) == set(zh-Hant)` | ✅ 203 = 203，无缺/多 |
| 空值 | 逐键 `strip()` | ✅ 0 |
| 占位符 | 正则 `@@[A-Z_]+@@`、`\{[a-z_]+\}` 逐键比对 | ✅ 0 不一致（13 键） |
| HTML 结构 | 标签序列逐键比对 | ✅ 0 不一致（20 键） |
| ASCII/代码 | 连续 ASCII 片段逐键比对 | ✅ 0 不一致 |
| 简体残留 | 用 OpenCC 词表构造「只可能是简体」字符集，逐键扫描 | ✅ 0 键残留 |
| 抽样词复查 | 42 个常见简体/大陆词扫描 | ✅ 0 残留（唯一「里」是「西里爾」，正确） |
| 预期台湾词出现 | 資訊/搜尋/使用者/介面/資料/檔案/載入/連結/專案/支援/廠商/警語/販售中/已下市… | ✅ 有源词的都出现；`預設/影片/軟體/列印/登入/繁體/簡體/資訊` 源文案没有这些词，故未出现（不是失败） |

---

## 5. 缺口与人工/AI 复查清单

自动转换已覆盖全部 203 键，但以下内容**必须人工复核后**才能上线为正式繁体文案：

| # | 项目 | 说明/例子 | 建议 |
|---|---|---|---|
| 1 | **专有名词/机构名** | 中國、國家醫保局、美國、英國、墨西哥、加拿大、西班牙（字符已转繁，但大陆官方名在部分法律语境可能应保留简体原名） | 产品/法务确认是否保留官方简体名；倾向：正文转换、引原文处保留 |
| 2 | **INN 中文名** | `对乙酰氨基酚→對乙醯胺基酚`（已按台湾药名）、`替尔泊肽/司美格鲁肽/利拉鲁肽/度拉糖肽` 等 GLP-1 名、`泰诺/泰诺林` 品牌名 | 对照台湾官方中文药名（TFDA/药典）逐条核；品牌名以原厂台湾写法为准 |
| 3 | **许可/法律表述** | About 许可段（AEMPS CIMA 条款、OGL v3.0、CC BY 4.0、WHO INN CC BY-NC-SA、© Commonwealth/His Majesty） | 保留英文条款原文；中文释义交法务/许可复核，不做机器再翻译 |
| 4 | **用词偏好** | `訪問統計`（可改「造訪/瀏覽統計」）、`檢索` vs `搜尋` 混用、`標識對應`、`示例`（可改「範例」）、`條` 量詞 | 台湾母语者通读一遍，统一口径 |
| 5 | **繁体字形选择** | `裡/臺/著/製/複` 等已按 TWVariants 与短语表处理；个别专名可能需 `臺` | 抽 3–5 页（首页/warn/About）目检 |
| 6 | **UI 渲染** | 20 个含 HTML 的键、13 个含占位符的键；繁体字符宽度与简体接近，但仍需页面级渲染（长句换行/CSS 无 media query 的老问题） | 接入 build.py 后按 `reports/i18n-audit` 的清单抽查 |
| 7 | **新键维护** | 未来 build.py 新增中文键不会自动出现在 zh-Hant | 接入时用 `{**zh, **zh_hant}` 兜底（回退简体），并在构建日志里 warning 未翻译键 |

---

## 6. build 接入建议（本任务不改 build.py，交建站 owner）

### 6.1 语言注册与路由

```python
# site/build.py（建议改动，不在本任务范围）
LANGS = [("en", "EN", ""), ("es", "ES", "es/"),
         ("zh", "中文", "zh/"), ("zh-Hant", "繁中", "zh-hant/")]
```

- 语言 code 用 **`zh-Hant`**（BCP-47，`<html lang="zh-Hant">`、hreflang 同一值）；路径用 `/zh-hant/`（与 `es/`、`zh/` 同模式，入口页 `page(..., lang="zh-Hant", alternates=True)`）。
- `i18n.js` 的 `pick()`：路径首段是 `zh-hant`，而 `D` 的 key 是 `zh-Hant`，需要在 `pick()` 里加映射（`{'es':'es','zh':'zh','zh-hant':'zh-Hant'}`），否则直入 `/zh-hant/` 会回落英文。
- `hreflang` 增加 `zh-Hant`，`x-default` 不变；sitemap 由 `build_seo_files()` 的 `rglob` 自动收 `/zh-hant/index.html`。
- 语言切换标签：`繁中`；`localStorage` 与 `?lang=zh-Hant` 沿用现有逻辑。

### 6.2 字典加载

```python
I18N_ZH_HANT = json.loads((ROOT / "data" / "i18n_zh_hant.json")
                          .read_text(encoding="utf-8"))["zh-Hant"]
# _merge_static_i18n(values) 之后：
I18N["zh-Hant"] = {**I18N["zh"], **I18N_ZH_HANT}   # 新键回退简体，避免缺键变英文
```

注意：`data/i18n_zh_hant.json` 里的 `@@PLACEHOLDER@@` 与 build.py 动态值需要**同样替换**（在 `_merge_static_i18n` 里对 zh-Hant 也跑一遍 `values` 替换），否则 About 页的统计数字会显示占位符。

### 6.3 体积与验收

- 字典 JSON raw ≈ 18.1 KB（gzip ≈ 5–6 KB）；当前 `i18n.js` 是三语内联，加 zh-Hant 后首屏 JS 增加同量级；若在意，可把 zh-Hant 拆成 `assets/i18n-zh-hant.js` 按语言懒加载（与 v0.5.x 的索引分片思路一致）。
- 验收（建议新增一个 `lib/test_i18n_hant.py`，只读数据文件）：
  1. `keys(zh) == keys(zh-Hant)`（203=203）；
  2. 无空值；
  3. 占位符/HTML 标签序列一致；
  4. 简繁残留扫描（复用本任务 `validation.json` 算法）为 0；
  5. 抽 3 页渲染 + hreflang 抽查。
- 范围提醒：增加 `zh-Hant` 属于**新语言入口**，上线前按 AGENTS.md 做全量建站验收（三语抽检 + 页数/索引回归 + 发布纪律）；建议 Lead 明确是否与 v0.6 一起发。

---

## 7. 复现命令与产物

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 下载/缓存 OpenCC 词典（仅首次联网；已缓存在 .tmp/zh-hant/）
& $py .tmp/zh-hant/fetch_opencc.py
& $py .tmp/zh-hant/fetch_tw.py
& $py .tmp/zh-hant/fetch_ts.py

# 2) 从 site/build.py 导出 zh 字典（只读 import，不运行 build）
& $py .tmp/zh-hant/export_zh.py

# 3) 生成 data/i18n_zh_hant.json + 校验
& $py .tmp/zh-hant/build_hant.py
```

| 产物 | 内容 |
|---|---|
| `data/i18n_zh_hant.json` | `_meta`（来源/词表许可/校验/人工复核标记）+ `"zh-Hant": {203 键繁体文案}` |
| `.tmp/zh-hant/zh_source.json` | 源 zh 字典（203 键，导出快照） |
| `.tmp/zh-hant/opencc_meta.json` / 5 个 OpenCC 词典 | 转换词表与来源记录 |
| `.tmp/zh-hant/validation.json` | 6 类校验 + 术语命中统计 + 抽样结果 |
| `.tmp/zh-hant/key_diff.json` | 180 个有改动键的 before/after |
| `.tmp/zh-hant/build_hant.py` / `export_zh.py` / `fetch_*.py` | 可复跑脚本 |

边界：**未改 `site/build.py`、未写 `data/drugs.db`、未跑 git/发布**；`data/i18n_zh_hant.json` 是数据文件，接入代码由建站 owner 按 §6 执行并重新建站验收。
