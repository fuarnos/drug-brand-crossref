# LG3（v0.15.0）：市场界面语言覆盖字段 + 测试门禁

> 2026-11-19 ｜ 工位 `phaseb-plan`（task-10）｜ 写权限：`data/markets.json`、`tests/`、`reports/`
> （Lead 2026-11-19 额外授权 `lib/markets.py` **仅 3 处**，见 §5）｜ 未写库、未改 `data/languages.json`、未改 `site/`、未 commit、未发布

## 0. 结论先行

| 项目 | 结果 |
|---|---|
| `data/markets.json` 15 个启用市场 | ✅ 每个都有 `ui_languages`（6 语）+ `ui_language_gaps`（**全覆盖也显式写 `[]`**），`json.load` 通过 |
| 母语未覆盖的市场（现查） | **只 3 个**：`JP→["ja"]`、`CZ→["cs"]`、`LV→["lv"]`；其余 12 个 `[]` |
| 门禁 `tests/test_markets_registry.py` | ✅ **Ran 57 tests — OK**（新增 `TestUiLanguageCoverage` 9 例，其中 **6 例反例**证明门禁不空转） |
| `& $py lib/markets.py --check` | ✅ `OK: 注册表校验通过`（exit 0，**0 错**） |
| `& $py deploy/i18n_check.py` | ✅ `FAIL 0`、exit **0**（WARN 数变化与本任务无关，见 §7） |
| 顺手修绿的预存在红 | ✅ §5：`ko` 进注册表时漏改 `lib/markets.py` 造成的 **13 红**（不是本任务引入） |

**一句话**：字段 + 门禁都落地了；「收了几万条数据却没有该语言界面」这件事，从此在数据层被写成显式声明、在测试层被卡住（缺字段 / 写错 / 谎报都会红）。

## 1. 字段语义（Lead 2026-11-19 确认：按**站点实际**）

| 字段 | 定义 | 为什么不是另一种写法 |
|---|---|---|
| `ui_languages` | 站点对该市场**真的渲染**的界面语言全集 = `data/languages.json` 里 `enabled: true` 的 code，按 `order` 排列 → 现查 6 个 `en/es/zh/zh-Hant/fr/ko` | 构建对**每个市场**都出全部语言页面（根=en、`/es/ /zh/ /zh-Hant/ /fr/ /ko/`；`site/dist/ko/coverage.html` 含全部 15 市场行）。若改写成「市场登记里的 `languages`」，会写出**假话**：`CA` 会被写成只有 `en`（漏官方 `fr`，且 `/fr/` 真渲染加拿大数据）、`US` 会被写成只有 `en`（漏 `/es/`） |
| `ui_language_gaps` | 该市场**母语**里未被 `ui_languages` 覆盖的 code；**全覆盖 = `[]`，不许省略、不许留空猜** | 这条才是用户 2026-11-19 那件事的落点：数据进来了、语言界面没有 → 显式写成缺口，覆盖页据此标 ⚠️ |

「母语」= 该市场商品名/数据实际使用的语言，人工声明，现查 15 条：

| 市场 | 母语 | `ui_languages` | `ui_language_gaps` |
|---|---|---|---|
| US 美国 | en | 6 语 | `[]` |
| GB 英国 | en | 6 语 | `[]` |
| CA 加拿大 | en + fr（双语官方） | 6 语 | `[]` |
| AU 澳大利亚 | en | 6 语 | `[]` |
| ES 西班牙 | es | 6 语 | `[]` |
| MX 墨西哥 | es | 6 语 | `[]` |
| CN 中国 | zh | 6 语 | `[]` |
| TW 中国台湾 | zh-Hant | 6 语 | `[]` |
| SG 新加坡 | en（站点按英文市场接入，官方另有 ms/ta → 本仓不声明、不做界面） | 6 语 | `[]` |
| HK 中国香港 | zh-Hant（英文名称层亦在 `languages`，已被覆盖） | 6 语 | `[]` |
| FR 法国 | fr | 6 语 | `[]` |
| EU 欧盟（region） | en（集中审批走英文/INN） | 6 语 | `[]` |
| **JP 日本** | **ja** | 6 语 | **`["ja"]`** |
| **CZ 捷克** | **cs** | 6 语 | **`["cs"]`** |
| **LV 拉脱维亚** | **lv** | 6 语 | **`["lv"]`** |

> `6 语` 即 `["en", "es", "zh", "zh-Hant", "fr", "ko"]`（15 行完全一致，顺序 = `languages.json` 的 `order`；测试按**列表精确相等**断言，重排/漏项都会红）。
> LG2 落地 ja/cs/lv 时，同一条门禁会逼着这两列同步改：`JP.ui_language_gaps` 从 `["ja"]` 变 `[]`、15 行的 `ui_languages` 加 `ja`。

## 2. 改动清单（`git diff --numstat`）

```
142  1   data/markets.json        ← 15 市场 × 9 行 + 顶层 updated
  8  2   lib/markets.py          ← Lead 授权，仅 3 处（见 §5）
183 10   tests/test_markets_registry.py
```

- `data/markets.json`：15 个 enabled 市场各在 `languages` 之后、`enabled` 之前插入两个字段；顶层 `updated` → `2026-11-19`。EU 区域层（`own_data: true`）位置同样在 `languages` 之后。
- 补丁脚本（可复跑、锚点唯一、失败不写文件）：`.tmp/lg3_add_ui_fields.py`（`.tmp/` 不入库）。dry-run 与正式跑都是「锚点替换 15 处 → `json.load` 复验 15 市场」。

## 3. 门禁设计（`tests/test_markets_registry.py`）

新增模块级纯函数 `ui_language_errors(markets, enabled_langs, native=None) -> list[str]`（空 = 通过），入参是 `markets.json` 的**原始 dict 列表**，因此可以喂假记录：

1. 每个 enabled 市场必须有 `ui_languages` / `ui_language_gaps`（**缺 → 红**）；
2. `ui_languages` 必须是非空字符串数组、无重复、每项都是 `languages.json` 里 **enabled** 的 code；
3. `ui_languages` 必须**恰好等于**站点渲染的界面语言全集（与 `order` 一致）—— 少写 = 谎报「仅英文」，多写 = 引用未启用语言；
4. `ui_language_gaps` 必须**恰好等于**「母语 − `ui_languages`」；市场母语未登记 → 红（新增市场不能悄悄过）。

`TestUiLanguageCoverage` 共 9 例：

| 用例 | 断言 |
|---|---|
| `test_gate_passes_on_real_registry` | 现查 6 语；真实注册表 0 问题 |
| `test_every_enabled_market_declares_both_fields` | 15 个 enabled 市场两字段都在、都是数组 |
| `test_ui_languages_are_the_six_rendered_ones` | 逐市场列表精确相等 |
| `test_gaps_match_native_language` | 逐市场 `gaps == 母语 − ui_languages`；且**只有** `{JP: [ja], CZ: [cs], LV: [lv]}` 非空 |
| `test_fake_market_missing_fields_fails` | **反例**：删掉两字段 → 报「缺 ui_languages / 缺 ui_language_gaps」 |
| `test_fake_market_wrong_gaps_fails` | **反例**：JP 缺口写成 `[]` → 报「ui_language_gaps 应为 ['ja']」 |
| `test_fake_market_shrunk_ui_languages_fails` | **反例**：只写 `["en"]`（「仅英文」）→ 报不一致 |
| `test_fake_market_with_disabled_ui_language_fails` | **反例**：混入 `de`（disabled）→ 报「未启用的界面语言 ['de']」 |
| `test_fake_market_without_native_language_fails` | **反例**：新市场没登记母语 → 报「未登记母语」 |

> 反例用的是「真实市场行 + 覆盖字段」的伪记录（`_fake()`），不依赖真实注册表被破坏；6 例全部断言**具体错误文案**，不是只断言「有错」，避免门禁退化成空转。

## 4. 验证记录（仓库根，逐条可复跑）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py -m unittest tests.test_markets_registry -v     # Ran 57 tests — OK（exit 0）
& $py lib/markets.py --check                          # OK: 注册表校验通过（exit 0）
& $py deploy/i18n_check.py --quiet                    # FAIL 0 / WARN 26 / INFO 26（exit 0）
& $py -c "import json;d=json.load(open('data/markets.json',encoding='utf-8'));print(len(d['markets']))"   # 15
```

改动前基线（同一命令，13:33 跑）为 **FAILED (failures=13)**，全部来自 §5 的预存在红；本任务改完后 **57/57 OK**。

`i18n_check` 的 `FAIL 0` 与 exit 0 与我改动前一致（该脚本只读 `site/build.py`、`data/languages.json`、`i18n_zh_hant.json`、`release_notes_i18n.json`、`CHANGELOG.md`、两个 CSV —— **不读 `markets.json`、不 import `lib/markets.py`、不读 `tests/`**），所以本任务的 3 个文件不可能影响它的判定。

## 5. 顺手修绿的预存在红（Lead 授权：`lib/markets.py` 仅 3 处）

`ko` 于 v0.13.8（2026-11-18，task-1）进 `data/languages.json` 时，`lib/markets.py` 的校验器与 `tests/` 没同步，**committed HEAD 上就是红的**：

```
& $py lib/markets.py --check   →  !! 校验失败 3 项
  - 语言 ko: script='hangul' 不在 ('latin', 'han', 'traditional', 'cyrillic', 'japanese', 'korean', ...)
  - 语言 ko: default_country 必填
  - 语言 ko: enabled 但默认市场  未注册
& $py -m unittest tests.test_markets_registry   → FAILED (failures=13)
```

3 处最小修法（`git diff --numstat` = `8  2  lib/markets.py`）：

| # | 位置 | 改动 |
|---|---|---|
| 1 | `ALLOWED_SCRIPTS` | 加 `hangul`（`db/schema.sql` 的 `name_key.script` 早就含 `hangul`，注册表校验器漏同步） |
| 2 | `_validate_languages()` | `default_country` 允许「纯界面语言」留空（仅当 `enabled` 时）；**未启用**的占位语言仍必须指向 `planned_markets` |
| 3 | `_validate_cross()` | enabled 但 `default_country` 为空的纯界面语言跳过「默认市场」交叉校验（ko 用户定「先接语言、不加 KR 市场」） |

测试侧同步（都是 ko 期望值）：`SITE_LANGS` 加 `("ko", "ko/")`、语言全集 10→11、enabled 语言 5→6、`hreflang_map` / `i18n_prefixes` 加 ko、CLI `--json` 语言数 10→11、`test_enabled_language_default_country_enabled` 对「无默认市场的 enabled 语言」改为断言 `market_for_language() is None`。

> 这 3 处没有放宽任何红线：enabled 语言仍必须有 enabled 的默认市场（除非它是显式声明的纯界面语言）；disabled 语言仍必须在 `planned_markets` 里指名默认国家。

## 6. 外部方案检索（AGENTS §12「先找现成工具」）

需求本质是「注册表数据契约 + 测试门禁」，不是新组件，所以按「能不能不自己写」检索了 3 条路：

| 候选 | 结论 | 原因 |
|---|---|---|
| `jsonschema`（Python，MIT） | **不采用** | 能给 `markets.json` 加 `required` / `enum`，但「`gaps` 必须等于母语减界面语言」这种跨字段推导仍要手写；且本仓零新增依赖、单测只用 stdlib，为一两个字段引入校验库不划算。若将来字段涨到 20+ 可再评估 |
| `babel` / CLDR likely-subtags（BSD） | **暂不采用，留作 LG2 后备** | 判断「en 是否覆盖 en-GB」「zh-Hant 是否被 zh 覆盖」用 CLDR 语言匹配最稳；现查 15 市场母语都写成精确 code（`ja/cs/lv/zh-Hant`），暂时不需要模糊匹配。LG2 加 `ja/cs/lv` 时若要「`zh` 覆盖 `zh-Hant`」这类判定，再引入 |
| `pytest` 参数化 / `unittest.subTest` | 采用 stdlib `unittest` | 仓库四套测试统一用 `unittest`，不另起一套 |

## 7. 已知缺口 / 交接注意事项

1. **`docs/市场扩展接口.md` 的字段文档没更新**（不在本任务写权限）：新增市场的 N 步清单里还应加「声明 `ui_languages` / `ui_language_gaps`」与母语登记要求。建议 Lead 收尾时补，或开 v0.15.x 文档小单。
2. **新字段不进 `lib/markets.py` 的 `Market.to_dict()`**（本轮按授权只改 3 处，没加第 4 处）：`python lib/markets.py --json` 不显示这两列；站点读 `markets.json` 原文（`json.loads`）不受影响。若要 CLI/构建统一从注册表对象取，需要再加一处 dataclass 字段。
3. **覆盖页渲染归 task-9（site-ui）**：本任务只交付数据 + 门禁。文案建议按现查写「界面语言 6 种 · 母语 ja 未覆盖」，**不要写「仅英文」**——站点对每个市场都出 6 语页面，JP 的问题是没有 **ja** 界面，不是只有英文。
4. **`i18n_check` WARN 从 2 涨到 26（`hardcoded=24`）与本任务无关**：本任务 3 个文件都不是它的输入（§4 末）。同期并行改动是 `site/build.py`（+119/−1，task-9，site-ui）与 `data/release_notes_i18n.json`（+36/−2，task-2，pages-deploy）；`hardcoded` 规则只扫 `site/build.py` 的字面量，请 site-ui 自查新加文案是否漏了 `data-i18n`（**不阻塞**：FAIL 仍 0、exit 0）。
5. **没跑**：`site/build.py`（不该在本任务跑，且 site-ui 正在改）、入库/写库（无窗口，本轮只读）。
