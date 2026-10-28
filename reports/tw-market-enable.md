# v0.7.0 启用窗口：TW 市场 + zh-Hant 语言（task-87）

> 日期：2026-10-28 ｜ 真实库只读（TW 16,457 产品已在库、无 HK/EU 写） ｜ **未改 `site/build.py` / `data/drugs.db` / git / 发布**
> 前置：task-81（v0.7.0 build.py TW 支持，`reports/tw-market-build.md`）验收通过；tw build 支持已就绪。
> 本任务：启用 `data/markets.json` TW + `data/languages.json` zh-Hant，修正注册表测试断言，跑校验/测试，SITE_OUT 构建验收，通知发布经理。

---

## 0. 结论

| 项 | 结果 |
|---|---|
| 配置启用 | ✅ `data/markets.json` TW `enabled=true`（source_id=tfda_tw、data_as_of=2026-10-22、notes 更新为已启用）；`data/languages.json` zh-Hant `enabled=true`（TW 默认语言、/zh-hant/ 路由） |
| 注册表校验 | ✅ `lib/markets.py --check` → `OK: 注册表校验通过`（exit 0） |
| 注册表测试 | ✅ `tests.test_markets_registry` **47/47 OK**（含 `test_enabled_markets_match_db_countries` 自动转绿：DB 8 国 = 启用 8 市场） |
| 其他测试 | ✅ lib **29/29**、etl **25/25**、mobile **29/29**；trilingual **68/72**（历史基线 67/72，失败为已知结构性断链、非本次回归，详见 §2.1） |
| SITE_OUT 构建 | ✅ 60,375 文件 / **436.3 MB**（core.json 32.2 MB，legacy index.json off）；无构建错误 |
| 四语产物 | ✅ `/`、`/es/`、`/zh/`、`/zh-hant/` 四语言目录均生成；zh-hant 首页/检索/About 出现 TW |
| 验收抽检 | ✅ 首页 TW option + Taiwan + 16,457 + hreflang="zh-TW"；drug 页矩阵 `data-country="TW"` 列；About 含 TFDA/OGDL/2026-10-22/16,457/品名解析；app.js/i18n.js `node --check` 通过 |
| 消息 | 已通知 Lead + 发布经理（index-p1）：**v0.7.0 启用完成，可构建发布** |

---

## 1. 配置变更（写范围：data/markets.json、data/languages.json、tests/test_markets_registry.py、本报告）

### 1.1 `data/markets.json`（TW）

```jsonc
"enabled": true,                    // was false
"order": 80,
"data_as_of": "2026-10-22",
"notes": "已启用（v0.7.0，2026-10-28）：TFDA「全部藥品許可證資料集」（data.gov.tw #9122，OGDL v1.0
  可再发布、须按「顯名聲明」署名）。真实库已入库 16,457 个在册产品（成分 token 映射 87.8%，
  规格由品名解析、置信度有限，页面需明示「規格来自品名解析」）。source_id=tfda_tw，
  data_as_of=2026-10-22，每 7 日更新。已知口径：成藥/中藥/植物提取物边界仍按草案排除，待产品/法务复核；
  TW 规格非结构化字段，D1 剂量对应按「品名解析、置信度有限」展示。"
```
- `source_id=tfda_tw` 保持不变（真实库 `source` 行已登记，task-71 SQL 已 apply）。

### 1.2 `data/languages.json`（zh-Hant）

```jsonc
"enabled": true,                    // was false
"default_country": "TW",            // unchanged
"path": "zh-Hant/", "hreflang": "zh-Hant",
"notes": "已启用（v0.7.0，2026-10-28）：繁体中文界面 /zh-hant/ 路由 + hreflang=zh-Hant；
  文案来自 data/i18n_zh_hant.json（台湾用语，机器转换 + 人工校对，专有名词/INN 保留）。
  TW 默认语言，zh-Hant 默认市场 TW（已启用）。"
```

### 1.3 `tests/test_markets_registry.py`（五处断言）

| 位置 | 变更 |
|---|---|
| 常量 `SITE_COUNTRY_I18N` | 加 `"TW"`（8 国） |
| 常量 `SITE_LANGS` | 加 `("zh-Hant", "zh-Hant/")`（4 语） |
| `TestMarkets.test_registered_market_set` | `country_order` / `enabled_markets` 集合加 `TW`（8） |
| `TestMarkets.test_i18n_keys_unique_and_match_existing_site_keys` | 注释改 8 国；断言随常量自动覆盖 `home.tw` |
| `TestLanguages.test_registered_language_set` | enabled languages 集合加 `zh-Hant` |
| `TestMarkets.test_tw_is_planned_placeholder` | `assertFalse(tw.enabled)` → `assertTrue`，注释 v0.7.0 已启用 |
| `TestLanguages.test_zh_hant_placeholder` | `assertFalse` → `assertTrue` + TW enabled 断言，注释更新 |
| `TestLanguages.test_site_langs_compatibility` | hreflang_map / i18n_prefixes 期望集合加 `zh-Hant` |
| `test_enabled_markets_match_db_countries` | **未改**：DB 已 8 国（含 TW），启用后自动转绿 |

---

## 2. 校验结果

```text
$py lib/markets.py --check
OK: 注册表校验通过                      # exit 0

$py -m unittest tests.test_markets_registry
Ran 47 tests in 0.675s
OK                                     # 47/47

$py -m unittest discover -s lib -t lib
Ran 29 tests in 1.014s
OK                                     # 29/29

$py -m unittest discover -s etl -t etl
Ran 25 tests in 0.006s
OK                                     # 25/25

$py -m unittest tests.test_mobile_inbox -v
Ran 29 tests in 6.972s
OK                                     # 29/29
```

### 2.1 trilingual 检索一致性测试

```text
$py tests/trilingual/run_tests.py      # 744.8s（全量 72 案例 / 354 查询）
案例 72（通过 68）；Top-5 命中 97.7%，Top-1 命中 96.0%；跨国可见 72/72
en: 123 查询 Top-5 119 / es: 116→113 / zh: 115→114
```

- **68/72 通过**（exit code 1，按脚本约定「全过才 0」）；**非本次启用引入的回归**：历史基线 `reports/trilingual-query-tests.md`（2026-10-26）为 **67/72**，本次反而 +1；4 个失败均为已记录的结构性断链，类型不变：
  - `metformin`（combo）：中文复方成分拆分断链（zh 未解析）；
  - `ciclosporin` / `beclometasone` / `chlorphenamine`（dup_inn）：同一药在中/英/西命名体系下有多个 substance 记录，en/es 落到另一条（已知重复成分问题，属 `reports/substance_duplicates.csv` / 合并任务范畴）。
- 本次启用窗口**未改检索/数据**（只改 markets/languages 配置 + 注册表测试），失败与配置无关；未硬改。若 Lead 要求 trilingual 100% 才能发布，需要另开检索/成分合并修复任务（非本窗口）。

---

## 3. SITE_OUT 构建验收（v0.7.0，TW/zh-Hant 已启用状态）

```powershell
$env:SITE_OUT='.tmp\dist-tw-enable'
& $py -X utf8 site\build.py
# == done ==（exit 0）
# name pages: 30383；combo pages: 10569；maker pages: 6997；confused 22；warnings 40
# core.json 32.2 MB（legacy index.json off）；total size: 436.3 MB
```

| 产物 | 实测 |
|---|---|
| 文件数 / 体积 | **60,375 文件 / 416.1 MiB（436.3 MB decimal）** |
| 语言目录 | `assets/ combo/ data/ drug/ es/ maker/ name/ zh/ zh-hant/`（四语言副本齐全） |
| 首页（en） | `value="TW"` ✓、`Taiwan` ✓、`16,457` ✓、`hreflang="zh-TW"` ✓、`home.tw` ✓ |
| 首页（zh-hant） | `/zh-hant/index.html` ✓、`value="TW"` ✓、`16,457` ✓、`hreflang="zh-TW"` ✓；i18n.js 含 `home.tw` + `台灣`/`台湾`（UI 文案走 i18n JS） |
| drug 页（acetaminophen） | `drug/acetaminophen.html` 含 `data-country="TW"` 矩阵列 ✓（8 国列） |
| About | `about.html` 含 `TFDA` ✓、`OGDL` ✓、`2026-10-22` ✓、`16,457` ✓、`品名`（規格解析说明）✓ |
| node 语法 | 运行环境 PATH 无 node；用 runtime node（`.../dependencies/node/bin/node.exe`）：`node --check assets/app.js` ✓、`i18n.js` ✓ |
| 0 字节/404 | 构建无报错；构建日志与文件数正常（详细静态 30/30 见 impl 报告，同一 build.py） |

---

## 4. 发布协调

- 已 `send_message` → **Lead** 与 **index-p1（发布经理，task-79 owner）**：**「v0.7.0 启用完成，可构建发布」**，附测试/校验结果与 dist 验收点；发布经理负责 build → publish → smoke → tag/Release。
- 备份/回滚清单保留（TW 入库前 `data/backups/drugs-before-tw-ingest-20261029.db`、`.tmp/tw-ingest/tw_write_manifest.json`），待线上 smoke 通过后再议删除。
- 本任务**未改 build.py / DB**；若发布验收发现 TW UI 问题，回滚配置：TW `enabled=false` + zh-Hant `enabled=false` + 测试断言回退（或由发布经理回滚源码）。

---

## 5. 风险 / 注意

| # | 风险 | 说明 |
|---|---|---|
| 1 | trilingual 全量测试超长 | 留后台；若失败需单独报；不影响本次配置/构建正确性（检索逻辑未改） |
| 2 | 首页 zh-hant 的 TW 显示名走 i18n.js（静态 HTML 只有 value="TW"） | 与 build.py 实现一致（v0.7.0 报告）；headless 验收已覆盖 |
| 3 | maker 页 TW 分组暂缺 | maker_candidates.csv 生成于 TW 入库前，需 data 侧重跑后自动出现（build 已支持）；非阻塞 |
| 4 | About 覆盖数字 | 自动来自 coverage 表；TW 16,457 已出现；发布前与 README/CHANGELOG 口径同步（发布经理/Lead） |
| 5 | 配置与 build.py 版本绑定 | v0.7.0 build.py 才支持 TW/zh-Hant；若回退 build.py 需同时回退本配置 |

---

## 6. 证据

| 文件 | 内容 |
|---|---|
| `.tmp/tw-enable/unittest_markets.out.txt` | markets 47/47 |
| `.tmp/tw-enable/lib_tests.out.txt` / `etl_tests.out.txt` / `mobile_tests.out.txt` | lib 29 / etl 25 / mobile 29 |
| `.tmp/tw-enable/trilingual_tests.out.txt` | trilingual 全量运行日志（进行中） |
| `.tmp/tw-enable/build.out.txt` | SITE_OUT 构建日志（== done ==） |
| `.tmp/tw-enable/preflight.py` | 启用前预检（配置副本校验/预期集合） |
| `.tmp/dist-tw-enable/` | 构建产物（436.3 MB，可删） |

---

_本报告由并行子智能体 data-depth 生成；未改 `site/build.py`、`data/drugs.db`、未 git/发布。_
