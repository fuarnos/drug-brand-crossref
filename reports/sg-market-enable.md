# v0.8.0 启用窗口：SG 市场（task-113 后续，Lead GO）

> 日期：2026-10-28 ｜ 真实库只读（SG 已于 task-113 落库） ｜ **未改 `site/build.py` / `data/drugs.db` / git / 发布**
> 前置：SG 真实库落库完成（`reports/sg-ingest-apply.md`）；impl-lazyload SG build 最终验收通过（rev6：矩阵 9 市场全显 + 移动端横滚）。
> 本任务：启用 `data/markets.json` SG + 更新注册表测试断言 + 全套测试 + SITE_OUT 构建验收 + 通知发布经理构建 v0.8.0。

---

## 0. 结论

| 项 | 结果 |
|---|---|
| 配置启用 | ✅ `data/markets.json` 新增 **SG**（enabled=true、source_id=hsa_sg、data_as_of=2026-08-07、order 85、lang en）；markets 10（9 国 + EU region 禁用），enabled markets **9**；languages **不变（4）** |
| 注册表校验 | ✅ `lib/markets.py --check` → `OK: 注册表校验通过` |
| 注册表测试 | ✅ `tests.test_markets_registry` **47/47**（两处断言加 SG + CLI JSON 市场数 9→10；`test_enabled_markets_match_db_countries` 自动转绿：DB 9 国 = enabled 9） |
| 其他测试 | ✅ lib **29/29**、etl **25/25**、mobile **29/29**；trilingual（见 §2.2） |
| SITE_OUT 构建 | ✅ `site/build.py` exit 0，**96.2s**；**62,878 文件 / 455.7 MB**（core 32.8 MB，sitemap 62,720 URL） |
| 矩阵 | ✅ **9 列全显** en 顺序 `US,GB,CA,AU,SG,CN,ES,MX,TW`（acetaminophen/atorvastatin/amlodipine 实测）；losartan 页含 SG 列；`.matwrap{overflow-x:auto}` 横滚 |
| SG 首页/检索 | ✅ 四语首页 `value="SG"` option；i18n.js 含 Singapore/Singapur/新加坡/home.sg；A-Losartan 品牌页 + 检索索引（shard-a）+ losartan 成分页 SG 列 |
| About | ✅ SG 5,511 行、HSA、SODL、2026-08-07、「在冊名冊 ≠ 在售」四语声明 |
| 消息 | 已通知 Lead + 发布经理（index-p1）：**v0.8.0 启用完成，可构建发布** |

---

## 1. 配置/测试改动

### 1.1 `data/markets.json`（新增 SG，TW 之后、EU 之前）

```jsonc
{
  "code": "SG", "kind": "country", "parent": null, "group": "ASIA",
  "name": { "en": "Singapore", "es": "Singapur", "zh": "新加坡" },
  "i18n_key": "home.sg", "flag": "🇸🇬",
  "source_id": "hsa_sg",           // 真实库 source.hsa_sg 已登记（SODL v1.0, data_as_of=2026-08-07）
  "extra_source_ids": [],
  "default_lang": "en", "languages": ["en"],
  "enabled": true, "order": 85,
  "data_as_of": "2026-08-07",
  "notes": "已启用（v0.8.0…）：data.gov.sg/HSA 在册名册（SODL v1.0，可再发布须署名+链许可；每 6 个月更新）；真实库 5,511 产品（成分映射 94.7%、规格 90.1%）；英文市场（无新语言）；『在冊名冊 ≠ 在售』；品牌名保留英文、成分中文走 inn_zh。"
}
```

### 1.2 `tests/test_markets_registry.py`（3 处，均为计数/集合同步）

| 位置 | 变更 |
|---|---|
| 常量 `SITE_COUNTRY_I18N` | 8 国 → 加 `"SG"`（9 国）；注释 v0.8.0 |
| `test_registered_market_set` | `codes` 集合加 `SG`；`country_order` / `enabled_markets` 集合 8→9 |
| `TestCliAndDocs.test_cli_json_output` | `len(data["markets"])` 9→**10**（SG 注册后 markets 总数；语言仍 10） |

> 语言/`zh-Hant`/TW 相关断言**不变**（4 语）；`test_enabled_markets_match_db_countries` 未改（DB 9 国 = enabled 9）。

---

## 2. 校验结果

### 2.1 配置与测试

```text
$py -m json.tool data/markets.json      # OK
$py lib/markets.py --check              # OK: 注册表校验通过
$py -m unittest tests.test_markets_registry
Ran 47 tests → OK                        # 47/47
$py -m unittest discover -s lib -t lib  # Ran 29 tests → OK
$py -m unittest discover -s etl -t etl  # Ran 25 tests → OK
$py -m unittest tests.test_mobile_inbox # Ran 29 tests → OK
```

### 2.2 trilingual 检索一致性

```text
$py tests/trilingual/run_tests.py   # 539.6s
案例 72（通过 68）；查询 354：Top-5 97.7%，Top-1 96.3%；跨国可见 72/72
en 123 查询 Top-5 119 / es 116→113 / zh 115→114
```

- **68/72** 与 v0.7.0 启用窗口一致（历史基线 `reports/trilingual-query-tests.md` 为 67/72）；4 个失败为**已知结构性问题**、非本次 SG 配置回归（检索/数据未改）：
  - `metformin`（combo）：中文复方拆分断链；
  - `ciclosporin` / `beclometasone` / `chlorphenamine`（dup_inn）：同名多 substance 的命名体系断链（成分合并任务范畴）。
- exit code 1 是脚本「全过才 0」约定；无需硬改。

---

## 3. SITE_OUT 构建验收（`.tmp/dist-sg-enable`）

```powershell
$env:SITE_OUT='.tmp\dist-sg-enable'; & $py -X utf8 site\build.py
# == done ==（exit 0，96.2s）
# drug pages 12,447 / name pages 31,139 / combo 10,942 / maker 6,997
# core.json 32.8 MB；sitemap 62,720 URL；total size 455.7 MB
```

| 验收点 | 实测 |
|---|---|
| 文件数 / 体积 | **62,878 文件 / 434.6 MiB（455.7 MB decimal）** |
| 首页四语 SG | `/`、`/es/`、`/zh/`、`/zh-hant/` 均 `value="SG"`；en 静态 Singapore；i18n.js Singapur/新加坡；覆盖行 5,511；hreflang zh-TW 保持 |
| 矩阵 9 列 | acetaminophen/atorvastatin/amlodipine：`['US','GB','CA','AU','SG','CN','ES','MX','TW']`（**无截断**，en 含 TW、zh 含 MX） |
| 移动端横滚 | `assets/style.css` `.matwrap{overflow-x:auto;-webkit-overflow-scrolling:touch}` 等 |
| SG 品牌检索 | `data/idx/shard-a-0.json` 含 A-Losartan；`name/a-losartan.html` 品牌页；`drug/losartan.html` 矩阵含 SG 列 |
| 复方页 SG | `combo/hydrochlorothiazide+losartan.html` 含 SG 产品（LOSARB PLUS 等 `tag sg`） |
| About | SG 5,511、HSA、SODL、2026-08-07、「在冊」声明均存在 |
| 其他 | 无 0 字节文件；sitemap/zh-hant 首页存在；`node --check` app.js/i18n.js = 0 |
| 静态验收 | `.tmp/sg-enable/accept2.py` → **41/41 PASS** |

---

## 4. 发布协调

- 已 `send_message` → **Lead** 与 **index-p1（发布经理）**：**v0.8.0 启用完成，可构建发布**（附 tests/校验/dist 验收点）。
- 发布经理负责：构建 → publish → smoke → tag/Release；本窗口**未跑 build 到 site/dist、未 publish**（构建产物在 `.tmp/dist-sg-enable`）。
- 备份/回滚保留：`data/backups/drugs-before-sg-20261028-1334.db`、`.tmp/sg-ingest/apply_manifest.json`；市场配置回滚 = 删除 SG 条目 + 测试断言回退（或发布经理回滚源码）。
- **注意**：v0.7.1 仍在发布流程中时，本任务只写 `data/markets.json`/tests（发布经理读已构建 dist，不受影响）；v0.8.0 构建须在 v0.7.1 发布完成后进行。

---

## 5. 风险 / 注意

| # | 风险 | 说明 |
|---|---|---|
| 1 | trilingual 全量运行 ~12 分钟 | 已知慢+已知基线 68/72；非 SG 配置回归（检索未改） |
| 2 | SG 品牌名不翻译 | 页面口径已定：品牌英文、成分中文 `inn_zh`、在册≠在售；build 已加 about.sg_source |
| 3 | 矩阵列数 | 已按 Lead 要求 9 市场全显 + 移动端横滚；losartan 等无 AU 产品页面只显示有数据的国家列（8 列） |
| 4 | 与 HK/EU 的关系 | 真实库已有 HK 枚举（无数据）、EU region 列（无数据）；markets 中 HK 未注册、EU 禁用，本窗口不涉及 |
| 5 | 发布顺序 | v0.7.1 publish 完成后再构建 v0.8.0；changelog/README 计数需发布经理/Lead 按 DB 现查（431,555 等）同步 |

---

## 6. 证据

| 文件 | 内容 |
|---|---|
| `.tmp/sg-enable/unittest_markets2.out.txt` | markets 47/47 |
| `.tmp/sg-enable/lib_tests.out.txt` / `etl_tests.out.txt` / `mobile_tests.out.txt` | 29/29、25/25、29/29 |
| `.tmp/sg-enable/trilingual_tests.out.txt` | trilingual 全量运行结果 |
| `.tmp/sg-enable/build.out.txt` | SITE_OUT 构建日志（== done ==，62,878 文件） |
| `.tmp/sg-enable/accept2.py` / `accept2.out.txt` | 41/41 静态验收（四语首页/矩阵 9 列/SG 品牌/About） |
| `.tmp/sg-enable/markets.with-sg.json` | 预检用 markets 副本 |
| `.tmp/dist-sg-enable/` | 构建产物（455.7 MB，可删） |
| 上游 | `reports/sg-ingest-apply.md`（真实库落库）、`reports/sg-ingest-prep.md`（task-104 副本验证） |

---

_本报告由并行子智能体 data-depth 生成；未改 `site/build.py` / `data/drugs.db` / git / 发布；v0.8.0 构建由发布经理执行。_
