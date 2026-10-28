# v0.8.0 新加坡（SG）市场接入（build.py）实现报告

> 任务：task-105（`site/build.py` 独占；SG 5,511 产品已由 data-depth 落库：products 431,555、components 534,246、coverage 9 行）。
> `data/markets.json` / `data/languages.json` / `tests/` / `data/drugs.db` / `site/dist` 均未改；构建：`SITE_OUT=.tmp/dist-sg`。
> **v0.8.0 修订（发布前 Lead 要求）**：版本号 v0.8.0（非 v0.7.2）；矩阵不再静默截断到 8 列，改为**全部市场列（9 列）都显示** + 移动端横向滚动。

## 0. 结果

| 项 | 结果 |
|---|---|
| 国家支持 | `COUNTRY_PRIORITY` 加 SG（en 序 US,GB,CA,AU,**SG**,CN,ES,MX,TW）；`U2_COUNTRIES` 加 SG；四语首页 `#country` 加 Singapore/Singapur/新加坡/新加坡；`.tag.sg` 徽章色 |
| 语言排序 | i18n.js `MORDER` 四语均含 SG：en `…AU,SG,CN…`；es `…AU,SG,CN,TW`；zh `CN,TW,SG,…`；zh-Hant `TW,CN,HK,SG,…`；下拉/chips 沿用 `COUNTRY_ORDER` 自动生效 |
| 覆盖徽章/覆盖表 | 首页覆盖行含 **SG 5,511**；About 覆盖表自动出现 SG 5,511 行（`coverage` 表驱动） |
| About / 许可 | 四语 `about.sg_source`：HSA「Listing of Registered Therapeutic Products」/ **SODL v1.0** 署名与许可链接 / data_as_of **2026-08-07**（每 6 个月）/ **在册名单不代表在售** / **商品名保留英文不翻译，中文仅成分名 inn_zh**；LICENCE_HTML 增加 HSA/SODL 条目（含官方要求署名文本 + 不暗示政府背书） |
| 搜索/索引 | country 字段自动含 SG（160,750 keys，+3,288）；SG 英文品牌可搜（抽样 A-Losartan 命中并标 SG）；解析条国家标签含 SG；无新语言/新 hreflang（英语市场） |
| warn/maker | 数据驱动自动包含 SG；抽样 maker 页已出现 SG 分组（msd-pharma-singapore-pte-ltd） |
| 矩阵 | SG 列并入 drug 页矩阵，**9 市场全部列都显示（不再截断）**：en `US,GB,CA,AU,SG,CN,ES,MX,TW`；zh `CN,TW,SG,US,GB,CA,AU,ES,MX`；zh-Hant 同 9 国按 TW 起序；列顺序由 i18n.js `MORDER` 按界面语言重排；`.matwrap` 横向滚动（移动端 390px 实测内部滚动 1159 > 362，页面不溢出） |
| 构建 | exit 0；**62,878 文件 / 455.7 MB**（较 SG 前 +9.5 MB）；sitemap **62,720**（+1,330）；drug 12,447（+201）/ name 31,139（+756）/ combo 10,942（+373）/ maker 6,997；core 32.8 MB、93 shards 70.3 MB |

## 1. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| `home.sg` 四语（Singapore / Singapur / 新加坡 / 新加坡） | L142/L298/L455；zh-Hant L799 |
| `about.sg_source` 四语（HSA/SODL/2026-08-07/在册≠在售/品牌不译） | en L1062 / es L1191 / zh L1303 / zh-Hant L800；About 渲染 L5632 |
| LICENCE_HTML HSA/SODL 署名条目 | L2123 |
| `COUNTRY_PRIORITY` 加 SG（矩阵/maker 默认序） | L4799 |
| 矩阵列上限移除（v0.8.0：全部市场列都显示，不再截断）；矩阵 `min-width` 860px（移动端 840px）+ `.matwrap` 横滚 | L4891–4897；CSS L2352/L2359 |
| 首页国家下拉 SG option | L5522 |
| `U2_COUNTRIES` 加 SG、chips 按语言序 | L3299 |
| `.tag.sg` 徽章色 | L2216 |
| MORDER 四语含 SG | L6608 |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-sg'; & $py -X utf8 site/build.py   # == done ==, exit 0
& $node --check .tmp\dist-sg\assets\app.js                      # 0
& $node --check .tmp\dist-sg\assets\i18n.js                     # 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-sg'    # 27/27 PASS
# 临时 http.server 8809 + headless.mjs（Chrome CDP）→ ALL CHECKS PASSED
```

- **静态 27/27**：四语首页 SG option；覆盖行 SG 5,511；`.tag.sg`；I18N 368×4 一致、home.sg/about.sg_source 四语；about.sg_source 含 HSA/SODL/2026-08-07/在册≠在售/品牌不译；About 根页 HSA/SODL/日期/覆盖表 `<td>SG</td>`+5,511；许可清单官方署名；MORDER 四语含 SG；U2 含 SG；drug acetaminophen/atorvastatin/amlodipine 矩阵含 SG（共 1,551 个 drug 页有 SG 列）；**矩阵 9 列且含全部市场 US/GB/CA/AU/SG/CN/ES/MX/TW（无缺失）**；core 含 SG；sitemap 62,720；抽样链接 0 404；无 0 字节。
- **Headless（Chrome CDP）**：en/es/zh/zh-Hant 下拉首项 US/ES/CN/TW，SG 文案 Singapore/Singapur/新加坡/新加坡；About en HSA/SODL/2026-08-07/SG 5,511/在册声明；About zh「在册名单不代表在售」；**drug en/zh 矩阵均 9 列且含全部 9 市场**（en `US,GB,CA,AU,SG,CN,ES,MX,TW`；zh `CN,TW,SG,US,GB,CA,AU,ES,MX`）；SG 品牌 A-Losartan 搜索命中并显示 SG；zh chips `CN,TW,SG,…` 含 SG；**移动端 390px：页面不溢出（390≤390）、矩阵容器内横滚（1159>362）、9 列全显示**。
- **数据核对**：coverage SG 5,511；source `hsa_sg` = HSA Listing of Registered Therapeutic Products，SODL v1.0，data_as_of 2026-08-07。

## 3. 风险 / 已知事项

1. **矩阵列数为 9（全部市场）**：v0.8.0 按 Lead 要求取消 8 列截断，US/GB/CA/AU/SG/CN/ES/MX/TW 全部显示；移动端靠 `.matwrap` 横向滚动（实测页面不溢出、容器内滚动 1159>362）。v0.6.6 的「矩阵 ≤8 列」规格已被本版本取代。
2. **SODL 署名**：About/许可清单使用数据要求的官方署名句（含访问日期 2026-10-28 与许可链接），并声明「不暗示政府背书」；SG 为英文注册名，中文只有成分名（inn_zh），品牌不翻译。
3. **数据截止 2026-08-07**（每 6 个月更新）；页面不写「在售」，只写注册名册。
4. **markets/languages 仍 disabled**：SG 由 build.py 内置支持，`data/markets.json`/`data/languages.json` 未启用（启用窗口由 data-depth/task-87 另做）；过渡期配置未启用但 UI 有 SG。
5. **maker 页**：SG MAH 已部分出现在 maker 分组（抽样 msd-pharma-singapore-pte-ltd）；`maker_candidates.csv` 若未重跑，部分 SG MAH 可能缺页（data 侧刷新后补齐）。
6. **无新语言/hreflang**：SG 是英语市场，不新增语言目录；sitemap 增量来自 SG 数据带来的 drug/name/combo 页（+1,330）。

## 4. 回滚

| 层次 | 操作 |
|---|---|
| 源码 | `git checkout -- site/build.py` 后重建/发布（Lead 执行） |
| 特性级 | 从 COUNTRY_PRIORITY/U2_COUNTRIES/下拉/MORDER 删 SG；删 home.sg/about.sg_source/LICENCE SG 条目/.tag.sg；矩阵恢复 8 列截断规则 |
| 发布后 | gh-pages revert 上一提交（SG 页面/索引会随数据重建，不含在源码回滚） |

## 5. 产物

- `site/build.py`：SG 国家支持、HSA/SODL 来源与署名、四语、矩阵 SG 列。
- `.tmp/dist-sg/`：构建产物（62,878 文件 / 455.7 MB）。
- 验收脚本：`static_check.py`、`headless.mjs`、`smoke.py`、`probe*.py`（TEMP `sg-build-verify-20261028/`）。
- `reports/sg-market-build.md`：本报告。
