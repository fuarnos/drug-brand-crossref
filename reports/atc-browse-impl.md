# v0.7.1 ATC 类别浏览 + 常见大类 实现报告

> 任务：task-82（`site/build.py` 独占，v0.7.0 之后；TW/四语/矩阵等既有功能不回归）。
> 数据只读 `data/drugs.db`（`substance.atc` / `entity_type.csv` 可选）；未改 `data/markets.json`、`data/languages.json`、tests、`data/drugs.db`、`site/dist`。
> 构建：`SITE_OUT=.tmp/dist-cat`。

## 0. 结果

| 项 | 结果 |
|---|---|
| ATC 类目页 | **1,154 页**（L1 14 / L2 93 / L3 249 / L4 798）`/atc/<prefix>.html`；父级/子级链接构成可逐级浏览的类目树；每页列成员成分（链 drug 页，上限 60） |
| 常见大类 | **16 个消费者大类** `/cat/<id>.html`（降压药、抗生素、降糖药、减肥药、感冒药、退烧止痛、抗过敏、胃药、抗凝、他汀、β受体阻滞剂、抗抑郁、哮喘/慢阻肺、激素、抗病毒、皮肤外用药）；映射 ATC 前缀并标「主题合集，不是同效等同」 |
| 入口 | `/atc.html` landing（14 个 L1 + 16 个大类）+ 顶部导航「ATC / 大类」+ 首页 16 个大类 chips（四语各自本地化） |
| 类名 | L1 用 WHO 14 大类四语名；L2–L4 内置常见类别四语名（C07 β受体阻滞剂、C10AA 他汀类、J01 抗菌药…）；未收录的显示 ATC 码 +「类别名待校订」；页面上明确「类别名是编辑/AI 译名，ATC 码为准」 |
| 搜索 | `data/categories.json`（54 条：16 大类 + 38 常见类别，含 1,154 个 atc_codes）；四语大类词（降压药 / beta blockers / antibióticos / 降壓藥）→ 主题合集结果 + 解析条「大类」+「不是同效」说明 + 类目页链接；ATC 码查询（C/C07/C07AB02…）解析条 + 「查看该 ATC 类别」链接（C07AB02 这类 L5 成分码回退到其 L4 类别 C07AB） |
| 许可 | About 许可清单新增 **WHO ATC/DDD Index** 引用（WHOCC 版权、不转载索引）+「类别名为编辑/AI 译名」说明；类目/大类页底部同源 notice |
| 四语 | ATC/大类新增 key 四语齐全；I18N **366 keys ×4 一致**；行内语言块（data-lang-inline）保证标题/链接内四语切换；zh-Hant 全繁體 |
| 构建 | exit 0；**61,547 文件 / 446.2 MB**（+9.9 MB）；sitemap **61,390 URL**（+1,171）；drug 12,246 / name 30,383 / combo 10,569 / maker 6,997 不变 |

> 说明：任务示例中的 **C07AB02** 是 ATC **L5 成分码**（本站成分页已是 drug 页），不在 L1–L4 类目页范围；搜索 C07AB02 仍返回该成分结果，并回退链到 L4 类目 `/atc/C07AB.html`（无 404）。

## 1. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| ATC/大类四语文案（28 keys） | `ATC_I18N` L5638；合并进 I18N L1522（en/es/zh）与 L1551（zh-Hant） |
| WHO ATC L1 四语名（14 类） | `ATC_L1_I18N` L5756 |
| L2–L4 常见类别四语名（25 个前缀） | `ATC_CLASS_I18N` L5782 |
| 16 个消费者大类（labels/desc/ATC 前缀） | `CONSUMER_CATEGORIES` L5830 |
| ATC 类目页生成（父/子类目树、成员、四语名、AI/来源 notice） | `build_atc_pages` L6010 |
| 大类专题页生成 | `build_category_pages` L6061 |
| landing `/atc.html` | `build_atc_index` L6102 |
| 客户端搜索数据 `data/categories.json` | `build_categories_json` L6133（atc_codes 为全部 1,154 前缀） |
| 首页大类 chips | 占位 `{cat_chips}` L5470；替换 L5509；生成 `_home_cat_chips` L6156 |
| 顶部导航 ATC 入口 | page() nav L4116 |
| 客户端：大类匹配（重音/空格不敏感）、大类渲染、ATC 类目页回退链接、解析条大类项 | APP_JS `catHit` L3361、`renderCategory` L3376；`parseBarHTML` 大类项；`renderATC` classCode 回退 |
| 行内语言块（`data-lang-inline=1` → inline） | i18n.js `apply()` 语言块显示逻辑 |
| CSS：`.atcgrid/.catgrid/.atccard/.atclist/.catchip/.catquick` | 样式表 ATC 段 |
| About WHO ATC/DDD 许可条目 | LICENCE_HTML L2080 |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-cat'; & $py -X utf8 site/build.py   # == done ==, exit 0
& $node --check .tmp\dist-cat\assets\app.js                      # 0
& $node --check .tmp\dist-cat\assets\i18n.js                     # 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-cat'    # 38/38 PASS
# 临时 http.server 8808 + headless.mjs（Chrome CDP）→ ALL CHECKS PASSED
```

- **静态 38/38**：1,154 ATC 页 / 16 大类页 / landing；categories.json（54 条、1,154 atc_codes、四语 labels、URL 全存在）；C/C07/C07AB 结构（类别名、父/子链接、成员、四语块）；大类页免责 + 相关 ATC + 成员；首页 16 chips、导航/About 许可；I18N 366×4、16 个 ATC key 四语；**ATC 页抽样 120 + 16 大类页站内链接 0 404**；sitemap 61,390；无 0 字节；体积 446.2 MB。
- **Headless（Chrome CDP）**：C 页子类 C01；C07 父类 C + zh 名 β受体阻滞剂；C07AB 父类 C07A + 英文名；大类页 zh「降压药」/免责/相关 ATC；landing 14 ATC + 16 大类；**四语大类搜索**（zh 降压药、en beta blockers、es antibióticos、zh-Hant 降壓藥）均命中类目页且解析条含大类说明；C07AB02 搜索有 ATC 解析条、结果含 β-blocker、回退链 `/atc/C07AB.html`。
- **404 修复**：有 ATC 但无 product 的成分（如 esomeprazole-magnesium）没有 drug 页，ATC/大类页成员列表改为**纯文本**（不链 `../drug/`），消除抽样 404。

## 3. 风险 / 已知事项

1. **类别名非官方**：L2–L4 仅 25 个常见类别有编辑/AI 四语名，其余以 ATC 码为标题并标「类别名待校订」；页面/About 均声明 ATC 码与 WHO 层级为准。
2. **C07AB02 不在类目页层级**：L5 成分码无 `/atc/C07AB02.html`，搜索走既有 drug/ATC 结果并回退到 L4 类目；如后续要 L5 类目页可加生成（约 +3,094 页 / +10 MB，本轮按任务 L1–L4 未做）。
3. **体积/页数**：+1,171 页 / +9.9 MB（446.2 MB）；发布经理已改增量上传，影响可控。
4. **大类是主题合集**：映射为 ATC 前缀规则（降压药 C02/C03/C07/C08/C09 等），不硬映射歧义词；页面/解析条/免责均写明「不是同效、不判断可互换」。
5. **客户端大类匹配**：按四语 label + 英文 id/别名精确匹配（忽略重音/空格），不做模糊匹配；词表新增需改 `CONSUMER_CATEGORIES` 重建。
6. **categories.json**：新增 ~14 KB 静态数据文件（含 1,154 atc_codes），随站点发布；搜索依赖它做类目链接，缺失时仅少「查看该类目」链接，不影响名称/ATC 搜索。

## 4. 回滚

| 层次 | 操作 |
|---|---|
| 源码 | `git checkout -- site/build.py` 后重建/发布（Lead 执行） |
| 特性级 | 移除 ATC_I18N/L1/CLASS/CATEGORIES 常量与 4 个 build_* 函数、main 调用、导航/首页 chips、APP_JS catHit/renderCategory/parse 大类项、categories.json、CSS、LICENCE ATC 条目 |
| 发布后 | gh-pages revert 上一提交（新增 /atc、/cat、/atc.html；删除后这些 URL 404，需整体回滚再重建） |

## 5. 产物

- `site/build.py`：ATC 类目/大类浏览、搜索大类词、WHO ATC 许可说明。
- `.tmp/dist-cat/`：构建产物（61,547 文件 / 446.2 MB）。
- 验收脚本：`static_check.py`、`headless.mjs`、`probe*.py`（TEMP `atc-browse-verify-20261028/`）。
- `reports/atc-browse-impl.md`：本报告。
