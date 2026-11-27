# v1.2.8 / LANG1-A：语言/市场注册表扩到 11 语 + `ui_language_gaps` 硬门禁进 CI

- 日期：2026-11-28（北京时间）
- 工位：`backend`（`task-1`）
- 版本：v1.2.8（LANG1-A 的「注册表 + 门禁」部分）
- 写域：`data/languages.json`、`data/markets.json`、`tests/test_markets_registry.py`、`deploy/ci_checks.py`、本报告
- 未碰：`site/build.py`（frontend 并发改）、`CHANGELOG.md`、`site/dist`、`data/drugs.db`；未 commit、未发布、未跑生产构建

## 结论

1. 界面语言 **9 → 11**：新增 `nb`（Norsk bokmål，`/nb/`，order 76）与 `ms`（Bahasa Melayu，`/ms/`，order 78），`data/languages.json` description 同步为 11 种。
2. 18 个市场的 `ui_languages` 全部追加 `nb`、`ms`（长度统一 11），并保持原有顺序；`default_lang`：**JP→ja、CZ→cs、LV→lv**；同时 **MY→ms、NO→nb**（`nb`/`ms` 的 `default_country` 分别指向 NO/MY，注册表交叉一致性要求市场默认语言跟它对齐，否则 `lib/markets.py` 交叉校验会红）。
3. **18 个市场 `ui_language_gaps` 全为 `[]`**，由规则「母语 − ui_languages」推导（不是手写）：MY 母语 `ms`、NO 母语 `nb` 都已被界面覆盖；`no` 是宏语言、由 `nb` 覆盖，不再单列缺口。
4. `tests/test_markets_registry.py` 新增硬断言 **「enabled 且有数据的市场，`ui_language_gaps` 必须为 `[]`」**（失败信息带市场码 + 缺口语言），并接进 `deploy/ci_checks.py` 的 `unittest:markets-registry`（fast / 全量都跑）——这条测试此前**从未进 CI**。
5. 本地证据：门禁单独加入时 **FAIL 2（MY/NO）** → 注册表改完 **61 tests OK**；`ci_checks.py --fast` **FAIL 0**，新 job 出现在输出里。

## 1. 改动明细

### 1.1 `data/languages.json`

| 字段 | `nb` | `ms` |
|---|---|---|
| code / native_name | `nb` / `Norsk bokmål` | `ms` / `Bahasa Melayu` |
| ui_label / hreflang / path | `NB` / `nb` / `nb/` | `MS` / `ms` / `ms/` |
| script / dir | latin / ltr | latin / ltr |
| default_country | `NO` | `MY` |
| enabled / order | true / 76 | true / 78 |
| name 字典 | en/es/zh（与现有 14 条语言条目结构一致；本族语名由 native_name 兜底） | 同左 |

- `description`：「当前启用 en/es/zh/zh-Hant/fr/ko/ja/cs/lv（9 种）」→ 「…/nb/ms（11 种）」，`updated` 改 `2026-11-28`。
- `ja` / `cs` / `lv` 的 `default_country` 由 `null` 改为 `JP` / `CZ` / `LV`（三市场现在默认这三种界面语言），并更新 notes 里「default_country 留空（市场数据默认英文）」的过时说明。`ko`（KR 默认 ko、但 default_country 仍为空的历史形态）不在本任务范围，未动。

### 1.2 `data/markets.json`

- 18 个市场的 `ui_languages` 统一为：`en, es, zh, zh-Hant, fr, ko, ja, cs, lv, nb, ms`；其它字段语义不变。
- `default_lang` / `languages`：
  - `JP`：`en` → `ja`，`languages` `["ja","en"]`
  - `CZ`：`en` → `cs`，`languages` `["cs","en"]`
  - `LV`：`en` → `lv`，`languages` `["lv","en"]`
  - `MY`：`en` → `ms`，`languages` `["ms","en"]`（nb/ms 的 default_country 交叉一致性）
  - `NO`：`en` → `nb`，`languages` `["nb","en"]`（同上）
- `ui_language_gaps` 全部 `[]`；notes 更新：
  - JP/CZ/LV：追加「v1.2.8 默认界面语言由 en 改为 ja/cs/lv」。
  - MY：原「马来语界面未接入 → ui_language_gaps=["ms"]」改为「ms 已启用（第 11 语言）、gaps=[]、默认语言 ms」。
  - NO：原「挪威语界面未接入 → gaps=["nb","no"]」改为「nb 已启用、gaps=[]、默认语言 nb；`no` 宏语言由 nb 覆盖」。NLOD 2.0 署名义务原文保留。
- `updated` 改 `2026-11-28`。文件保持 CRLF，UTF-8 不转义中文，缩进 2 空格。

### 1.3 `tests/test_markets_registry.py`

- 新增 `TestUiLanguageCoverage.test_enabled_markets_with_data_have_no_gaps`：
  - 遍历 `data/markets.json` 的 enabled 市场；
  - 「有数据」：DB 存在时按 `product.country` / `product.region` 现查（17 国 + EU region）；DB 缺失（GitHub Actions 无库）时按 enabled 视为有数据；
  - 断言 `ui_language_gaps == []`，失败信息写清市场码与缺口语言；
  - 末尾断言至少覆盖 18 个「有数据的启用市场」，防止空转。
- 同步既有期望：11 语集合、`SITE_LANGS` 加 `nb`/`ms`、`MARKET_NATIVE_LANGS["NO"] = ("nb",)`（`no` 宏语言由 nb 覆盖）、JP/CZ/LV/MY/NO 的默认语言与 `languages`、KR/MY/NO 的 `ui_languages` 长度 9 → 11、语言总条数 14 → 16、gap 期望表由 `{"MY":["ms"],"NO":["nb","no"]}` 改为空表。
- 反例测试保留：假市场缺字段 / 谎报缺口 / 少写 ui_languages / 引用 disabled 语言 / 未登记母语，仍必须红（门禁不空转）。

### 1.4 `deploy/ci_checks.py`

- `check_unittests()` 新增：`_run_unittest("unittest:markets-registry", ["tests.test_markets_registry"])`，fast 与全量都跑（不设 `if fast` 分支）。
- `SUMMARY_ORDER` 插入 `unittest:markets-registry`；模块 docstring 的 fast 清单同步。
- 理由：`tests/test_markets_registry.py` 从 2026-10 起只存在、从未进 CI，注册表 / 界面语言覆盖漂移无人拦（本次补的漏洞）。

## 2. 改前 / 改后证据（命令 + 数字）

### 2.1 改前基线（未加新门禁）

```powershell
& $py -m unittest tests.test_markets_registry -v
```

```
Ran 60 tests in 0.642s
OK
```

### 2.2 只加新门禁、未改注册表（复现 FAIL 2）

```powershell
& $py -m unittest tests.test_markets_registry -v
```

```
FAIL: test_enabled_markets_with_data_have_no_gaps (tests.test_markets_registry.TestUiLanguageCoverage.test_enabled_markets_with_data_have_no_gaps) (market='MY')
FAIL: test_enabled_markets_with_data_have_no_gaps (tests.test_markets_registry.TestUiLanguageCoverage.test_enabled_markets_with_data_have_no_gaps) (market='NO')
Ran 61 tests in 0.712s
FAILED (failures=2)
```

失败信息（节选）：`市场 MY 已启用且有数据，但 ui_language_gaps=['ms']；缺口语言 ['ms'] 必须先补界面语言再上线`、`市场 NO … ['nb','no'] …`。

### 2.3 改完后（PASS）

```powershell
& $py -m unittest tests.test_markets_registry -v
```

```
Ran 61 tests in 0.754s
OK
```

### 2.4 语法检查

```powershell
& $py -m py_compile deploy/ci_checks.py
```

```
PY_COMPILE_EXIT=0
```

### 2.5 CI fast（新 job 已生效）

```powershell
& $py deploy/ci_checks.py --fast
```

```
[PASS] unittest:markets-registry Ran 61 tests in 0.727s | OK（0.8s）
[PASS] py_compile         190 个 Python 文件编译通过（本次编译 3 个，缓存复用 187 个）
[PASS] dist-integrity     362,112 文件 / 0 字节 0（fast-抽样：抽查 500 个） / sitemap 230,435 URL（5 分片合计）
14 项：PASS 9 / FAIL 0 / SKIP 5（总 52.2s · mode=fast · dist=site/dist）
CI_EXIT=0
```

（fast 总耗时 52.2s，其中 etl 单测 34.1s；本任务新增 job 自身 0.8s，未改变其它判定。`--fast` 的 5 项 SKIP 均为原有「全量才跑」项。）

### 2.6 只读证明：18 市场 / 11 语 / 默认语言 / gaps

只读脚本（读两个 JSON，不写任何东西）：

```powershell
@'
import json
from pathlib import Path
m = json.loads(Path("data/markets.json").read_text(encoding="utf-8"))["markets"]
l = json.loads(Path("data/languages.json").read_text(encoding="utf-8"))["languages"]
enabled = [x["code"] for x in l if x["enabled"]]
print("enabled_langs =", enabled, "| count =", len(enabled))
print("markets =", len(m), "| enabled =", sum(1 for x in m if x["enabled"]))
bad = [x["code"] for x in m if "nb" not in x["ui_languages"] or "ms" not in x["ui_languages"]]
print("18 市场 ui_languages 缺 nb/ms 的:", bad or "无")
want = {"JP": "ja", "CZ": "cs", "LV": "lv", "MY": "ms", "NO": "nb"}
print("default_lang 核对:", {k: next(x["default_lang"] for x in m if x["code"] == k) for k in want})
print("非空 ui_language_gaps:", {x["code"]: x["ui_language_gaps"] for x in m if x["ui_language_gaps"]} or "无（18/18 全空）")
print("ui_languages 长度集合:", sorted({len(x["ui_languages"]) for x in m}))
print("nb/ms 语言条目:", {x["code"]: (x["path"], x["hreflang"], x["ui_label"], x["default_country"], x["order"]) for x in l if x["code"] in ("nb", "ms")})
'@ | & $py -
```

输出：

```
enabled_langs = ['en', 'es', 'zh', 'zh-Hant', 'fr', 'ko', 'ja', 'cs', 'lv', 'nb', 'ms'] | count = 11
markets = 18 | enabled = 18
18 市场 ui_languages 缺 nb/ms 的: 无
default_lang 核对: {'JP': 'ja', 'CZ': 'cs', 'LV': 'lv', 'MY': 'ms', 'NO': 'nb'}
非空 ui_language_gaps: 无（18/18 全空）
ui_languages 长度集合: [11]
nb/ms 语言条目: {'nb': ('nb/', 'nb', 'NB', 'NO', 76), 'ms': ('ms/', 'ms', 'MS', 'MY', 78)}
```

### 2.7 注册表 CLI 校验

```powershell
& $py lib/markets.py --check
```

```
OK: 注册表校验通过
```

### 2.8 diff 规模

```
 data/languages.json            |  56 ++++++++++++++++---
 data/markets.json              | 104 ++++++++++++++++++++++------------
 deploy/ci_checks.py            |  12 ++--
 tests/test_markets_registry.py | 123 +++++++++++++++++++++++++++--------------
 4 files changed, 209 insertions(+), 86 deletions(-)
```

（JSON 两个文件与测试文件保持原 CRLF；`deploy/ci_checks.py` 保持 LF。）

## 3. 规则推导说明（为什么 MY/NO 的 gaps 可以是 `[]`）

- 门禁规则仍是「gaps = 市场母语 − `ui_languages`」，测试里的 `MARKET_NATIVE_LANGS` 是母语登记表。
- `MY` 母语 `("ms",)`：新增 `ms` 界面后覆盖，推导 `[]`。
- `NO` 母语原写 `("nb","no")`：`no` 是 ISO 639 宏语言代码，`nb`（Bokmål）就是站点要提供的挪威语书面界面，两者不是两种可独立渲染的界面语言。若继续要求 `no`，会逼出一个并不存在的独立界面语言；因此把母语表改为 `("nb",)`，并在注释里写明「`no` 宏语言由 nb 覆盖」。这是**规则输入修正**，不是给 NO 手写 `gaps=[]`。
- 市场 `default_lang` 与语言 `default_country` 的交叉约束由 `lib/markets.py` 的 `validate()` 保证：`nb.default_country=NO` ⇒ `NO.languages` 必须含 `nb`、且测试要求 `NO.default_lang=nb`；`ms` 与 `MY` 同理。故本次除任务书点名的 JP/CZ/LV 外，MY/NO 的默认语言也必须跟到 `ms`/`nb`，否则注册表自校验与既有交叉测试会红。

## 4. 外部方案检索（AGENTS §12）

| 候选 | 能解决什么 | 不采用原因 |
|---|---|---|
| [`jsonschema`](https://github.com/python-jsonschema/jsonschema) | 用 JSON Schema 校验注册表结构 | 需新增第三方依赖 + 维护 `.schema.json`；本仓现有 `lib/markets.py` 已有字段/唯一性/交叉校验，unittest 直接复用即可 |
| [`langcodes`](https://github.com/rspeer/langcodes) | BCP 47 解析、语言码规范化、`nb`/`no` 关系 | 固定 11 个语言码，`lib/markets.py` 的 `RE_LANG`/`RE_HREFLANG` 已够；引入依赖收益低 |
| [`Babel`](https://babel.pocoo.org/) | CLDR 语言/地区数据、本地化名称 | 体积大（CLDR 数据），站点构建是 stdlib + 静态产物，不需要运行时 locale 数据 |

结论：**不新增依赖**，沿用「`lib/markets.py` 校验 + stdlib `unittest` 门禁 + CI 脚本」的现有做法；本任务只补一条硬断言与 CI job，符合仓库「无 npm / 静态构建 / 零新增支出」的边界。

## 5. 验收对照

| 任务书验收项 | 结果 | 证据 |
|---|---|---|
| ① 改前 FAIL 2（MY/NO）/ 改后 PASS，命令与输出行数写进报告 | ✅ | §2.2（61 tests, FAILED failures=2）、§2.3（61 tests OK） |
| ② `py_compile deploy/ci_checks.py` | ✅ | §2.4，exit 0 |
| ③ `ci_checks.py --fast` PASS 且新 job 出现 | ✅ | §2.5，`PASS 9 / FAIL 0 / SKIP 5`，`[PASS] unittest:markets-registry … 61 tests` |
| ④ 只读证明 18 市场含 nb/ms、JP/CZ/LV 默认语言、MY/NO gaps=[] | ✅ | §2.6 输出 |
| 写域限制（不碰 build.py / CHANGELOG / dist / db；不 commit / 不发布） | ✅ | 本报告 §1 写域；`git status` 中 `site/build.py` 的改动属 frontend |

## 6. 剩余与风险（交给 Lead / 下游）

1. **`site/build.py` 未完成前不要跑生产构建**：本任务只改注册表与门禁；frontend 正在把 `nb`/`ms` 接进 `LANGS` / I18N 字典。本报告的 `test_site_langs_compatibility` 已按 11 语写好，frontend 落地后需由 release 工位跑全量构建与三语/十一语抽检。
2. **`deploy/i18n_check.py` 的 `LANGS` 仍是 9 语**：它不校验 `nb`/`ms` 的 I18N 字典（本任务未改该文件，也不在写域）。nb/ms 字典写入 `site/build.py` 后，建议另开任务把 i18n_check 扩到 11 语，否则这两个新语言的键集/伪翻译覆盖率不在 CI 覆盖内。
3. **发布侧同步**：`deploy/verify_live.py` 的 `LANG_ROOTS`、`deploy/fix_fr_root.py` 注释需随实际线上语言路由由 release 工位确认（本工位不发布）。
4. **未跑**：trilingual、`db/check_data.py`、生产构建、R2 发布——均不属于本任务验收，且按工位纪律不执行。

## 7. 复现命令汇总

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING = 'utf-8'

& $py -m unittest tests.test_markets_registry -v      # 61 tests OK
& $py -m py_compile deploy/ci_checks.py               # exit 0
& $py lib/markets.py --check                          # OK: 注册表校验通过
& $py deploy/ci_checks.py --fast                      # PASS 9 / FAIL 0 / SKIP 5
```
