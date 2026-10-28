# 繁中字典补全：247 → 328 键（task-75）

> 日期：2026-10-28 ｜ 对象：`data/i18n_zh_hant.json`（zh-Hant 文案字典）
> 产物：补全后的 `data/i18n_zh_hant.json`（328 键）· 本报告 · `.tmp/zh-hant3/`（zh 快照、刷新脚本、校验明细、刷新前备份）
> 边界：**未改 `site/build.py`、未写 `data/drugs.db`、未跑 git/发布**；只更新数据文件与报告。

---

## 1. 结论

| 指标 | 刷新前 | 刷新后 |
|---|---:|---:|
| 键数 | 247 | **328**（= 当前 `site/build.py` I18N zh 全量） |
| 新增键 | — | **81**（删除 0） |
| 实际有转换差异的键 | 223 | **283** |
| 空值 | 0 | **0** |
| 占位符 / HTML / ASCII 结构问题 | 0 | **0** |
| 残留简体字（抽样扫描） | 0 | **0** |
| 键集合与 zh 一致 | ✅ | ✅ 328 = 328 |
| 字符量 | 7,296 | 8,396 |
| 文件体积 | 23,718 B | 29,000 B |

- 任务要求的 **328 键全部有 zh-Hant 文案**（此前 81 键会回退简体）；`_meta.refresh` 记录 `previous=247 / keys=328 / new_keys=81 / removed=[]`。
- 旧 247 键中只有 **2 个值有改进**：`parse.match.prefix`（字首→**前綴**，与 ATC 前缀统一）、`about.sources`（程式碼→**代碼**，避免把药品代码误用程序代码译法）；其余 245 键保持不变。

---

## 2. 新增 81 键分组

| 分组 | 键数 | 内容 |
|---|---:|---|
| `glossary.*` 术语表 | **31** | 页面标题/导语/列头（术语/含义）+ 14 组代码解释：INN、BAN、USAN、ATC、MAH、DIN、NDC、ARTG、FDC、LASA/tall-man、OTC、Rx、规格/强度 |
| `form.*` 剂型 | **13** | 片剂→**錠劑**、胶囊、液体、注射剂、外用、粉末、栓剂、吸入剂、微丸、棒剂、套装→**套裝**、气体、未知 |
| `release.*` 释放机制 | **4** | 缓释、**延迟释放**、**改良释放**、— |
| `unit.*` 单位 | **7** | 国际单位→**國際單位**、单位、**毫當量**、mCi、mcg、mcg、10 万 IU→**10 萬 IU** |
| `u1.*` 使用引导 | **10** | 三步看懂、输入包装上的名字、看成分和规格、切国家看叫法、各 step hint、试试、关闭、使用引导 |
| `u2.*` 各国叫法 | **5** | 各国叫法、未收录、未收录说明、多成分/多结果等 |
| `nav.glossary` / `meta.glossary.*` | **3** | 术语表导航 + 术语表页 title/description |
| `parse.atc` / `parse.match.atc` / `atc.*` | **8** | ATC 码、ATC 匹配方式、索引提示（按 ATC 码前缀匹配）、命中/空结果/加载文案 |
| **合计** | **81** | |

样例（zh → zh-Hant）：

| key | zh | zh-Hant |
|---|---|---|
| `glossary.intro` | 包装、监管记录和本站里常见代码/术语的简短解释。只帮助读代码，不是医疗建议。 | 包裝、監管記錄和本站裡常見代碼/術語的簡短解釋。只幫助讀代碼，不是醫療建議。 |
| `form.tablet` | 片剂 | **錠劑** |
| `form.kit` | 套装 | **套裝** |
| `unit.meq` | 毫当量 | **毫當量** |
| `release.DR` | 延迟释放 | **延遲釋放** |
| `u2.none_hint` | 公开数据里暂无该国该成分的产品；不等于该国没有这个药。 | 公開資料裡暫無該國該成分的產品；不等於該國沒有這個藥。 |
| `atc.hint` | 按 ATC 码前缀匹配：结果是「活性成分带有该 ATC 码」的产品，不是商品名匹配。 | 按 ATC 碼前綴匹配：結果是「活性成分帶有該 ATC 碼」的產品，不是商品名匹配。 |
| `meta.glossary.title` | 术语表 · 药品商品名跨国定位 | 術語表 · 藥品商品名跨國定位 |

---

## 3. 转换规则与新增术语

沿用既有流水线（task-53/68，未改算法）：单次扫描 → 自建 `TW_TERMS` → OpenCC `TWPhrases/STPhrases` → 逐字 `STCharacters` → `TWVariants`；OpenCC 词典（Apache-2.0）只读复用 `.tmp/zh-hant/`。

本轮新增 16 条台湾术语/断词保护（`TW_TERMS` 135 → **151**）：

| 大陆/简体写法 | 台湾写法 | 说明/命中 |
|---|---|---:|
| 代码 | **代碼** | 6 处；关键：不能走 OpenCC TWP 的「代码→程式碼」（那是程序代码） |
| 术语 / 术语表 | **術語 / 術語表** | 3+3 |
| 前缀 / 码前缀匹配 | **前綴 / 碼前綴匹配** | 2+1；统一 ATC/匹配方式用词（弃用「字首」） |
| 片剂 | **錠劑** | 剂型页关键台湾用语 |
| 套装 | 套裝 | 1 |
| 棒剂 / 栓剂 / 吸入剂 | 棒劑 / 栓劑 / 吸入劑 | 字符转换 + 术语保护 |
| 延迟释放 / 改良释放 | 延遲釋放 / 改良釋放 | release.* 标签 |
| 国际单位 / 毫当量 | 國際單位 / 毫當量 | unit.* 标签 |
| 三步看懂 / 使用引导 | 三步看懂 / 使用引導 | u1 引导 |

---

## 4. 校验（`validation.json` 内置；失败不写文件）

| # | 校验项 | 结果 |
|---|---|---|
| 1 | JSON 可解析（UTF-8） | ✅ |
| 2 | 键集合 = 当前 I18N zh | ✅ 328 = 328（无缺、无多、0 删除） |
| 3 | 无空值 | ✅ 0 |
| 4 | 占位符一致（`@@X@@`、`{code}`、`{n}` 等 15 个键） | ✅ 0 不一致 |
| 5 | HTML 标签结构一致（20 个键） | ✅ 0 不一致 |
| 6 | ASCII/代码标识一致 | ✅ 0 不一致 |
| 7 | 残留简体字扫描（OpenCC 词表构造的简体字符集） | ✅ **0 键** |
| 8 | 常见简体/大陆词抽样（42 词） | ✅ 0 残留 |
| 9 | 旧 247 键稳定性 | ✅ 仅 2 个改进（前綴、代碼），其余不变 |
| 10 | 新增键数/分组 | ✅ +81 / 0 removed |
| 11 | `zh == zh-Hant` 的键 | 45 个（繁简同形/专名，正常） |

字符量 8,392 → 8,396（+4）；文件 23,718 → 29,000 B（gzip 预估 +1.5 KB 量级）。

---

## 5. 接入注意（build.py 侧，本任务未改代码）

1. **键集完整**：`I18N['zh']` 合并后 328 键；加载 zh-Hant 用 `{**I18N['zh'], **hant}` 兜底（未来新键回退简体，不会变英文）。
2. **新占位符**：`atc.hit` 使用 `{code}` / `{n}`（与 zh 相同），`atc.none_meta` 使用 `{code}`——接入时确认 build.py 对 zh-Hant 做同样的格式化/替换。
3. **新页面类型**：`glossary.title/intro/...` 对应术语表页，`nav.glossary` 需进导航；`meta.glossary.*` 会直接进 `<title>`/description，需人工审校（SEO 用词与长度）。
4. **剂型/释放/单位标签**：「錠劑/膠囊/套裝/微丸/棒劑」等台湾用语已按台湾优先转换，建议上线前用真实产品页抽检（片剂→錠劑、缓释→緩釋、毫当量→毫當量）。
5. **语言注册**：与 task-53 报告 §6 一致——`LANGS` 加 `("zh-Hant","繁中","zh-hant/")`、`<html lang="zh-Hant">`、hreflang `zh-Hant`、`/zh-hant/` 静态入口、i18n.js `pick()` 的 `zh-hant → zh-Hant` 映射。

---

## 6. 人工/AI 复查清单（本轮新增）

| 优先级 | 项目 | 说明 |
|---|---|---|
| P1 | 31 条 `glossary.*` 术语解释 | 涉及 INN/BAN/USAN/ATC/MAH/DIN/NDC/ARTG/FDC/LASA/OTC/Rx 的繁体表述与药名译名（如 `對乙醯胺基酚`、`二甲雙胍`、`格列本脲`）需具备药事背景者复核 |
| P1 | `meta.glossary.title/desc` | 会直接进 SEO 标题/描述，长度与台湾搜索习惯需确认 |
| P2 | 剂型用词 | `錠劑`（tablet）、`套裝`（kit）、`微丸`（pellet）、`棒劑`（stick）在台湾说明书里的实际用词建议抽对 TFDA 用语 |
| P2 | ATC 相关 | `ATC 碼` vs `ATC 代碼`、`前綴` vs `字首`（本轮统一为「碼/前綴」） |
| P3 | 澳大利亚/澳洲 | 本轮用「澳大利亞」（OpenCC 字符转换）；台湾口语常用「澳洲」，可按品牌风格统一 |

---

## 7. 复现与产物

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 从当前 site/build.py 导出 zh 全量（只读 import，不跑 build）
& $py .tmp\zh-hant3\_probe.py    # 首次导出得到 zh_source；亦可用 zh-hant2/export_zh_refresh.py 改路径
# 2) 转换 + 校验 + 写回 data/i18n_zh_hant.json
& $py .tmp\zh-hant3\build_hant_refresh2.py
# 3) 复核统计
& $py .tmp\zh-hant3\stats.py
```

| 产物 | 内容 |
|---|---|
| `data/i18n_zh_hant.json` | 328 键 zh-Hant；`_meta.refresh` 记录 247→328 / +81 / 0 removed |
| `.tmp/zh-hant3/zh_source.refresh2.json` | 本次导出 zh 快照（328 键） |
| `.tmp/zh-hant3/i18n_zh_hant.before-refresh2.json` | 刷新前备份（247 键） |
| `.tmp/zh-hant3/validation.json` / `key_diff.json` | 11 项校验 / 有改动键 before-after |
| `.tmp/zh-hant3/build_hant_refresh2.py` / `stats.py` / `review.py` | 可复跑脚本（词典只读复用 `.tmp/zh-hant/`） |

边界：只改 `data/i18n_zh_hant.json` 与新增报告；**未改 `site/build.py`、`data/drugs.db`，未跑 git/发布**。
