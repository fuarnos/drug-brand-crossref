# 繁中字典刷新：203 → 247 键（task-68）

> 日期：2026-10-28 ｜ 对象：`data/i18n_zh_hant.json`（zh-Hant 文案字典）
> 产物：刷新后的 `data/i18n_zh_hant.json`（247 键）· 本报告 · `.tmp/zh-hant2/`（导出快照、刷新脚本、校验明细、刷新前备份）
> 边界：**未改 `site/build.py`、未写 `data/drugs.db`、未跑 git/发布**；只更新数据文件与报告。

---

## 1. 结论

| 指标 | 刷新前 | 刷新后 |
|---|---:|---:|
| 键数（= `site/build.py` 当前 I18N zh 全量） | 203 | **247** |
| 新增键 | — | **44**（0 个键被删除） |
| 实际有转换差异的键 | 180 | **223** |
| 空值 | 0 | **0** |
| 占位符/HTML/ASCII 结构问题 | 0 | **0** |
| 残留简体字（抽样扫描） | 0 | **0** |
| 键集合与 zh 一致 | ✅ | ✅ 247 = 247 |
| 字符量 | 6,743 | 7,296 |
| 文件体积 | 20,003 B | 23,718 B |

> 任务预估约 233 键，**实际 247**：build.py 在 v0.5.6 又新增了 `meta.*`（10）、`combo.cross_*`（9）、`a1.*`（11）、`res.*`（8）等；本轮按"当前 build.py 全量"导出，超出预估属正常。

- 44 个新键**全部完成转换**，键集合与 zh 完全一致；旧 203 键中只有 **5 个值发生变化**（2 个因中文源文更新、3 个因新增台湾术语），其余保持原样。
- 新增 14 条台湾术语/断词保护（`TW_TERMS` 从 121 条增至 135 条），并对 1 个歧义键做显式覆盖（`report.field_row`：行→列）。

---

## 2. 新增 44 键（按功能分组）

| 分组 | 键数 | 键 | 说明 |
|---|---:|---|---|
| 结果表格复制/下载 | 8 | `res.copy`、`res.csv`、`res.copied`、`res.copy_fail`、`res.col_country`、`res.col_form`、`res.col_match`、`res.col_link` | 复制表格、下载 CSV、列头（国家/剂型/匹配方式/页面） |
| 产品明细展开 | 11 | `a1.expand`、`a1.loading`、`a1.none`、`a1.goto`、`a1.market`、`a1.pack`、`a1.approval`、`a1.status`、`a1.source`、`a1.raw`、`a1.more` | 详情/加载中/打开成分页/市场/包装/批准号/状态/来源/原始记录 |
| 盐型/释放/警示 | 3 | `a3.salt`、`a3.release`、`a3.incompat` | 盐型：、释放：、不可互换 — 见警語 |
| 表格行操作 | 2 | `row.report`、`report.field_row` | 回報這一列 / 列（row→台湾用语「列」） |
| What's new 待补提示 | 1 | `whatsnew.pending` | 中文原文；英/西語譯文待補 |
| 组合页跨市场 | 9 | `combo.cross_title` / `cross_exact` / `cross_products` / `cross_record` / `cross_overlap` / `cross_none` / `cross_primary` / `cross_primary_link` / `cross_unmatched` | 其他国家/地区的同组合等（只做身分對應，不代表可互換） |
| 页面元信息 | 10 | `meta.index.title/desc`、`meta.about.title/desc`、`meta.confused.title/desc`、`meta.warn.title/desc`、`meta.whatsnew.title/desc` | SEO title/description（v0.5.5 三语页头） |
| **合计** | **44** | | |

样例（zh → zh-Hant）：

| key | zh（源） | zh-Hant |
|---|---|---|
| `meta.index.title` | 药品商品名跨国定位 — 跨国家/语言的药品名对照 | 藥品商品名跨國定位 — 跨國家/語言的藥品名對照 |
| `meta.warn.desc` | 已发布的警示：同名不同药，以及跨国、盐型或释放机制下不可互换的复方产品。 | 已發布的警語：同名不同藥，以及跨國、鹽型或釋放機制下不可互換的複方產品。 |
| `combo.cross_exact` | 这些市场收录了成分组合完全相同的产品。只做身份对应，不代表可以互换或替代。 | 這些市場收錄了成分組合完全相同的產品。只做身分對應，不代表可以互換或替代。 |
| `row.report` | 报告这一行 | 回報這一列 |
| `report.field_row` | 行 | 列 |
| `a1.goto` | 打开成分页 | 開啟成分頁 |
| `res.csv` | 下载 CSV | 下載 CSV |
| `whatsnew.pending` | 中文原文；英/西语译文待补。 | 中文原文；英/西語譯文待補。 |

---

## 3. 转换规则与新增术语

沿用 task-53 的流水线（未改算法）：**单次扫描** → 自建台湾术语 `TW_TERMS` → OpenCC `TWPhrases/STPhrases` → 逐字 `STCharacters` → `TWVariants` 字形 → 术语兜底；OpenCC 词典（Apache-2.0）仍为 task-53 缓存，本轮只读。

新增 14 条术语/断词保护（`TW_TERMS` 112→135，含本轮专有 14 条）：

| 大陆/简体写法 | 台湾写法 | 命中 |
|---|---|---:|
| 合并 / 合并后的名称 | 合併 / 合併後的名稱 | 1 |
| 身份对应 | 身分對應 | 3 |
| 报告这个结果 / 报告这一行 | 回報這個結果 / 回報這一列 | 1+1 |
| 这一行 | 這一列 | 1 |
| 更新说明 | 更新說明 | 2 |
| 批准号 | 批准號 | 1 |
| 原始记录 | 原始記錄 | 2 |
| 详情 | 詳情 | 1 |
| 加载明细 | 載入明細 | 1 |
| 打开成分页 | 開啟成分頁 | 1 |
| 跨市场对照 | 跨市場對照 | 1 |
| 编辑规则 | 編輯規則 | 1 |

另对 **`report.field_row`（值只有单字「行」）** 做显式覆盖为「列」——台湾表格术语 row=列、column=行，单字走全局映射会误伤「银行/进行」等词，因此只对这一个键覆盖。

**旧 203 键中 5 个值有变化**（均在预期内）：

| key | 变化原因 |
|---|---|
| `whatsnew.lang_note` | 中文源文在 v0.5.5 更新（改为"英文/西语更新说明为 AI 机器翻译…"） |
| `combo.capped` | 中文源文占位符从 `@@COMBO_CAP@@` 改为 `{cap}/{total}`（同步保留） |
| `report.cta` | 新术语：報告這個結果 → **回報**這個結果 |
| `about.rules`、`combo.intro` | 新术语：身份对应 → **身分**對應 |

---

## 4. 校验（`validation.json`，脚本内置；失败不写文件）

| # | 校验项 | 结果 |
|---|---|---|
| 1 | JSON 可解析（UTF-8） | ✅ |
| 2 | 键集合 = 当前 I18N zh | ✅ 247 = 247（无缺、无多、0 删除） |
| 3 | 无空值 | ✅ 0 |
| 4 | 占位符一致（`@@X@@`、`{cap}` 等；13 个键） | ✅ 0 不一致 |
| 5 | HTML 标签结构一致（20 个键） | ✅ 0 不一致 |
| 6 | ASCII/代码标识一致 | ✅ 0 不一致 |
| 7 | 残留简体字扫描（OpenCC 词表构造的简体字符集） | ✅ **0 键** |
| 8 | 常见简体/大陆词抽样（42 词） | ✅ 0 残留 |
| 9 | 台湾用语出现（有源词的） | ✅（`資訊/介面/登入/預設/專案/影片/軟體/列印/繁體/簡體` 源文中没有，故未出现，不是失败） |
| 10 | 新增键数/分组 | ✅ +44 / 0 removed |
| 11 | `zh == zh-Hant` 的键（繁简同形） | 24 个（成分、品牌、活性成分、剂型匹配方式等，正常） |

字符量 7,291 → 7,296（+5，正常）；`_meta.refresh` 记录 `Previous_keys=203 / keys=247 / new_keys=44 / removed_keys=[]`。

---

## 5. 接入注意（build.py 侧，本任务未改代码）

1. **运行期完整键集**：`I18N['zh']` 已在 `_merge_static_i18n` 后包含 BASE/ABOUT/PAGE/WARN/combo/meta 共 247 键；加载 zh-Hant 时用 `{**I18N['zh'], **hant}` 兜底（未来新键回退简体，不会变英文）。
2. **新式占位符**：`combo.capped` 已从 `@@COMBO_CAP@@` 改为 `{cap}/{total}`，接入时 zh-Hant 值需和 build.py 的格式化方式（`.format(cap=…, total=…)` 或等价）保持一致；本轮已保留与 zh 相同的占位符。
3. **`meta.*` 会直接进 `<title>`/description**：10 条新元信息文案是本轮最需要人工审校的部分（SEO 用词/长度）。
4. **语言注册**：`LANGS` 增加 `("zh-Hant", "繁中", "zh-hant/")`、`<html lang="zh-Hant">`、hreflang `zh-Hant`、`/zh-hant/` 静态入口、i18n.js `pick()` 的 `zh-hant → zh-Hant` 映射——与 task-53 报告 §6 的建议相同。
5. **验收**：rebuild 后抽 `/zh-hant/` 首页 + 一个药物页 + What's new 三语块，检查 a1 明细展开、res 复制/下载按钮、combo 跨市场文案；字典 JSON 增加约 3.7 KB（gzip 约 +1 KB），可接受。

---

## 6. 人工/AI 复查清单（本轮新增）

| 优先级 | 项目 | 说明 |
|---|---|---|
| P1 | 10 条 `meta.*` SEO 文案 | 「跨國定位」「跨國家/語言」等表述需确认台湾搜索习惯；description 长度控制在 ~120–155 字符 |
| P1 | `row.report`/`report.field_row` 的「列/行」 | 台湾：row=列、column=行；已按此转换，需母语者确认 |
| P2 | 「身分」vs「身份」 | 本轮按台湾教育部标准用「身分」；如团队偏好「身份」可回退 1 条术语 |
| P2 | 「回報」vs「報告」 | 语境为“反馈数据错误/回報这一列”，用「回報」；若觉得过口语可回退 |
| P3 | `a1.approval`「批准號 / NDC / DIN」 | NDC/DIN 保留英文（法规编号惯例）；其余字段措辞抽检 |

---

## 7. 复现与产物

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 从当前 site/build.py 导出 zh 全量（只读 import，不跑 build）
& $py .tmp\zh-hant2\export_zh_refresh.py
# 2) OpenCC+台湾术语流水线转换 + 校验 + 写回 data/i18n_zh_hant.json
& $py .tmp\zh-hant2\build_hant_refresh.py
# 3) 复核统计
& $py .tmp\zh-hant2\stats_refresh.py
```

| 产物 | 内容 |
|---|---|
| `data/i18n_zh_hant.json` | 247 键 zh-Hant 字典；`_meta.refresh` 记录 203→247、44 新增、0 删除 |
| `.tmp/zh-hant2/zh_source.refresh.json` | 本次导出 zh 快照（247 键） |
| `.tmp/zh-hant2/i18n_zh_hant.before-refresh.json` | 刷新前备份（203 键） |
| `.tmp/zh-hant2/validation.json` / `key_diff.json` | 校验明细 / 有改动键的 before-after |
| `.tmp/zh-hant2/build_hant_refresh.py` / `export_zh_refresh.py` / `stats_refresh.py` | 可复跑脚本（词典只读复用 `.tmp/zh-hant/`） |

边界：只改 `data/i18n_zh_hant.json` 与新增报告；**未改 `site/build.py`、`data/drugs.db`，未跑 git/发布**。
