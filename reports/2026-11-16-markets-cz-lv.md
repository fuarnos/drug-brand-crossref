# v0.13.0 市场注册表：CZ / LV（task-2，工位 phaseb-plan）

- 日期：2026-11-16（北京时间）｜约束：**不写 `data/drugs.db`、不改 `site/build.py`、不 commit、不发布**
- 范围：`data/markets.json`、`tests/test_markets_registry.py`、`docs/市场扩展接口.md`、本报告
- 结论：注册表侧 15 市场（14 国 + EU region）/ 5 语配好；`lib/markets.py --check` 通过、`tests.test_markets_registry` **48 项全绿**；DB 窗口已写 CZ 68,581 / LV 18,766（全库 594,781）

## 1. 改了什么

| 文件 | 改动 | diff |
|---|---|---|
| `data/markets.json` | 新增 CZ / LV（照 JP 结构），顶层 `updated` → 2026-11-16 | +51/−1 |
| `tests/test_markets_registry.py` | `SITE_COUNTRY_I18N` +CZ/LV；v0.13.0 版本注释（14 国/5 语）；市场集合 13→15、CLI JSON 13→15；新增 `test_cz_lv_market_rows` | +36/−7 |
| `docs/市场扩展接口.md` | 两处计数改 15 市场（14 国 + EU region）/ 14 国下拉，未新增章节 | +2/−2 |

行尾 / 编码：三个文件保持仓库现状 **UTF-8 无 BOM + CRLF**（`git ls-files --eol` = `i/crlf w/crlf`），未整文件改写。

## 2. CZ / LV 字段表（与 ETL / DB source 表对齐）

| 字段 | CZ | LV |
|---|---|---|
| kind / parent / group | country / null / EUROPE | country / null / EUROPE |
| order | 130 | 140 |
| i18n_key / flag | home.cz / 🇨🇿 | home.lv / 🇱🇻 |
| source_id | **sukl_dlp**（ETL 登记值） | **zva_lv_register**（`lv.py:SOURCE_ID`） |
| extra_source_ids | [] | [] |
| default_lang / languages | en / ["en"]（不新增 UI 语言，同 JP） | en / ["en"] |
| enabled / data_as_of | true / **2026-11-01**（DLP `platnost_od`） | true / **2026-11-11**（ZIP/状态表 Last-Modified） |
| 五语名 | Czechia / Chequia / 捷克 / 捷克 / Tchéquie | Latvia / Letonia / 拉脱维亚 / 拉脫維亞 / Lettonie |

notes 口径：CZ = SÚKL 开放数据条款（须署名、不改含义、SPC/PIL 不取不发布、排除 FSMP/PZLU 1,451 行、EU/ 集中审批 13,385 行去重）；LV = ZVA HumanProducts CC0 1.0（仍惯例署名、包装级 40,600 → 注册号 18,766、EU 集中审批 1,561 去重）；两者都写「授权/收载 ≠ 当前在售」。
> `data_as_of` 取 **DB `source.data_as_of` 语义（源自己的日期）**，与 phaseb-data 写库值一致（JP 同型：版本日 2026-11-01、抓取日 2026-11-12）。

## 3. 校验（可复核）

```powershell
& $py lib/markets.py --check
& $py -m unittest tests.test_markets_registry -v
```

| 检查 | 结果 |
|---|---|
| JSON / 15 市场 / UTF-8 | ✅ `markets 15 updated 2026-11-16` |
| `lib/markets.py --check`（读真库 source 表） | ✅ `OK: 注册表校验通过`，exit 0 |
| `lib/markets.py --json` | ✅ 15 市场 / 15 enabled；CZ/LV 的 i18n_key + source_id 见 §2 |
| `unittest tests.test_markets_registry -v` | ✅ **48 项 OK**，exit 0（DB 国家集合 / source 表 / 五语 / dummy 注册 / CLI） |
| DB 对账（只读） | ✅ `product.country` 14 国 = `country_order`；CZ=68,581、LV=18,766；source.data_as_of 与注册表一致 |
| 站点侧（只读 grep） | ✅ `site/build.py` 五语 `home.cz`/`home.lv`、`COUNTRY_PRIORITY` 含 CZ/LV、两处下拉 option 均在 |

## 4. 文档 N 步清单核对（只读，只报告不扩范围）

1. ~~步骤 9 发布入口过时（写 `deploy/publish.ps1`）~~ → 已在本次并行修改中改为 `deploy/sync_r2.ps1`（唯一通道）+ `verify_live`，§8 末项同改。
2. **步骤 6 检索用例未覆盖**：`tests/trilingual/*` 无 CZ/LV 样本（要求新市场 ≥3 个成分用例）→ 建议 Lead 排后续小任务。
3. **§2.1 字段模板缺 `data_as_of`**：TW/SG/HK/FR/JP/CZ/LV 实际都在用，模板未列（不影响校验）。
4. ~~`docs/许可清单.md` CZ source id 写 `sukl_cz_dlp`~~ → phaseb-data 已在本窗口改成 `sukl_dlp`，已一致。
5. **§7 EU runbook 与实现不一致**：写「成员国将来 `parent:"EU"`」，实际 FR/CZ/LV 均 `parent=null`（非阻塞）。
6. 步骤 2「先 `enabled:false` 提交」：CZ/LV 与 JP 一样在窗口完成后直接 `enabled:true`，文档流程与实际有偏差（非阻塞）。

## 5. 剩余

- 注册表侧无剩余；trilingual CZ/LV 用例、`docs/市场扩展接口.md` 的 publish.ps1 过时表述属后续小任务（本工位只报不改）。全量构建后请抽检首页下拉 / 覆盖页 CZ、LV 两行 / About 署名（`data_as_of` 由 source 表自动带出）。
