# v0.6.0 组合页跨市场同组合区块 实现报告

> 任务：task-61（`site/build.py` 独占，v0.5.6 之后）。输入：`data/combo_match_candidates.csv`（5,713 行）、
> `reports/combo-crossmatch.md`。
> 改动文件：**仅 `site/build.py`**。未跑 git/发布、未改 `site/dist`、`data/drugs.db` 或其他跟踪文件；
> v0.5.6 的 detail buckets / lazy-load 逻辑未动。构建：`SITE_OUT=.tmp/dist-combo`。

---

## 0. 结果

| 项 | 数值 |
|---|---|
| 组合页 | **9,291**（与索引唯一 `cu` 一一对应，数量不变） |
| 跨市场区块 | 全部 9,291 页都有；四类互斥覆盖：**exact 326 · overlap 8 · none 4,509 · unmatched 4,448** |
| 映射覆盖 | 页面原始 sids 集合 → CSV 归一名数签名：**4,843 / 9,291（52.1%）**；其余显示中性提示（不臆断 exact/none） |
| 体积 | 总计 **57,839 文件 / 450.4 MB**（含 v0.5.6 detail buckets 46.9 MB）；组合页目录 **+2.44 MB**（43.53→45.97 MB，平均 +262 B/页） |
| 三语 | 新增 `combo.cross_*` **9 键 × en/es/zh**；I18N 三语 key 数量一致、无 `@@` 残留 |
| 无 404 | 抽样 120 个组合页站内链接全部存在；8 个 overlap 页的近似组合链接存在；HTTP 19/19、DOM 2/2 |

## 1. 接入方案与实现（`site/build.py`）

### 1.1 页面 sids → CSV 签名映射（核心）
组合页的 `vs` 是「同一 name_key 下所有产品的成分并集」，不一定等于单个产品成分集合（报告 §5.4 已提示）。
构建期做两级反查，**不猜测**：

1. **产品级精确反查**：扫描 `product_component` 全部产品 → 每个产品原始 sids 集合 → 若该集合恰好等于某组合页的
   `vs`，则用产品成分归一后的签名 `a|b|c` 匹配 CSV（覆盖率主来源）；
2. **页级归一并集兜底**：页面 sids 归一后的集合并集若恰好是 CSV 某签名，也建立映射。

仍对不上的页面（页名合并了多个不同产品）显示**中性提示**「无法对该合并名称做跨市场对照」，
不把「无法判断」误报成 exact 或 none。

### 1.2 四类区块（紧凑渲染，构建期完成，零运行时开销）

| 类型 | 渲染 |
|---|---|
| `exact` | 一行说明（只做身份对应、不构成可互换建议）+ `<ul class="xlist">` 每市场一行：`国家 · 品牌(≤3) · N products · record`，`record` 链样例产品的品牌页（无品牌页则成分页），最多 8 个市场 |
| `overlap≥0.80` | warn 样式说明「相近但不相同——不可互换」+ 近似组合列表（同名组合页有页则链 `./<slug>`，否则纯文本） |
| `none` | 一行「其他已收录市场暂无同组合」；`primary_cross_market=yes` 时追加「仅主成分相同，不是同一个复方」+ 主成分链接 `../drug/<sid>.html` |
| `unmatched` | 一行中性提示（见 1.1） |

`brands` 为空的市场（如美国仿制药商品名挂在 `inn` 下）回退显示该市场主成分/generic 名，不留空。

### 1.3 实现位置

| 内容 | 位置 |
|---|---|
| 跨市场三语文案（9 键） | `COMBO_I18N`：en L1169–1183 / es L1206–1221 / zh L1239–1253 |
| 列表样式 `.xlist`/`.x-mkt` | CSS L1735–1737 |
| ETL 归一化复刻（同义词 + 盐/酯词 + `norm_ingredient`） | L3448–3489 |
| CSV 读取（构建期只读） | `load_combo_matches()` L3490–3505 |
| 映射：`prod_sids`/`tuple_sig`/`page_sig`/`sig_pages` | `build_combo_pages` L4076–4118 |
| 样例产品链接（品牌页/成分页回退）、区块渲染 | `_record_link` L4124、`cross_html` L4134–4195 |
| 注入页面正文（品牌表/截断提示之后） | L4258 |

### 1.4 要求 2 的保持
- 结果行/组合页入口逻辑**未改**：复方 `x` 含 ` + ` 时成分列用索引 `cu` 进组合页；单成分进 `drug/<sid>.html`。
- `app.js` 未修改；DOM 抽样确认 Excedrin 复方成分→组合页、Lipitor 单成分→成分页。
- none 的主成分降级链接有独立标签与警示文案，不与「同复方」混淆。

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-combo'; & $py -X utf8 site/build.py   # == done ==, exit 0
& $node --check .tmp\dist-combo\assets\app.js                      # 0
& $node --check .tmp\dist-combo\assets\i18n.js                     # 0
& $node --max-old-space-size=4096 .tmp\dist-combo\_verify\dom.test.mjs  # 2/2 PASS
& $py -X utf8 .tmp\dist-combo\_verify\static_check.py                   # 32/32 PASS
# 临时 http.server 8801 + http_check.mjs → 19/19 PASS
```

- **静态 32/32**：组合页数 == 索引唯一 `cu`；9,291 页全有区块；exact 326 / overlap 8 / none 4,509 / unmatched 4,448 四类互斥且全覆盖；
  三语 9 键齐全、无 `@@`；`.xlist` 样式；抽样 120 页内部链接全存在（无 404）；overlap 页近似组合链接全部存在；
  产物无 0 字节、index ≥5 MB。
- **样例（任务指定）**：
  - 阿莫西林 + 克拉维酸 → `exact`，列 CA/CN/ES/MX/US 等市场、品牌、产品数、record 链接（样例产品→品牌页）；
  - 二甲双胍 + 格列本脲 → `exact`，CN（唐柯柠/立将/齐亭…274）+ US（30）；US 品牌为空回退成分名，无空 `—`；
  - 复方氨酚烷胺（acetaminophen+amantadine）→ `none` + 「仅主成分相同，不是同一个复方」+ 主成分 `drug/<sid>.html` 链接（文件存在）；
  - overlap 页 8 个，链接指向存在的近似组合页。
- **HTTP 19/19**：三个样例页 200 且含对应区块/三语 key/data-label；`i18n.js` 含三语 cross 文案；
  `style.css` 含 `.xlist`；`index.json` 含 `cu`；首页正常。
- **体积增量**：同为 9,291 页，组合页目录 43.53 MB（v0.5.5）→ 45.97 MB（v0.6.0），**+2.44 MB**（平均 +262 B/页）；
  总产物 450.4 MB（其中 v0.5.6 的 detail buckets 46.9 MB 非本任务引入）。

## 3. 风险 / 已知问题

1. **映射覆盖 52.1%**：4,448 个页面的 `vs` 是多个不同产品的成分并集，无法安全对应到单一 CSV 签名 → 显示中性提示，
   不展示 exact/none。若要求全覆盖，需要 ETL 侧输出「页面 slug ↔ 签名」映射表（本任务写范围不含 ETL）。
2. **CSV 是 2026-10-28 快照**（DB 持续更新）：DB 变化后需重跑 `etl/build_combo_matches.py`，否则区块与当前产品不一致。
3. **归一化规则在 build.py 内复刻**（同义词 30+、盐/酯词表）：若 ETL 更新词表，需同步 `norm_ingredient`/`_COMBO_*`，
   否则映射率会下降（不会误报）。
4. **exact 只表示「成分集合相同」**：不校验规格/剂型/释放机制（与报告设计一致），页面文案明确「identity only」。
5. **体积**：v0.6.0 总计 450.4 MB（区块 +2.4 MB）；发布拷贝/gh-pages 时间随总量上升，需关注。
6. `brands` 为空时回退主成分名是展示降级，不改变匹配判断；overlap 仅 8 个签名（CSV 口径），样本很小。
7. 页面数、索引、结果行逻辑均未变；v0.5.6 的懒加载/detail buckets 未受影响。

## 4. 回滚

| 层次 | 操作 |
|---|---|
| 源码 | `git checkout -- site/build.py` 后重建/发布（Lead 执行） |
| 特性级 | ① `build_combo_pages` 删除映射块/`cross_html` 调用；② 删 `COMBO_I18N` cross 9 键；③ 删 `.xlist` CSS；④ 删 `norm_ingredient/load_combo_matches` 及词表 |
| 发布后 | gh-pages revert 上一提交（仅组合页内容与 i18n 字典变化，无数据/索引结构变化） |

## 5. 产物

- `site/build.py`：`norm_ingredient`/`load_combo_matches`/映射与 `cross_html`/COMBO_I18N 9 键/`.xlist` CSS。
- `.tmp/dist-combo/`：构建产物（57,839 文件 / 450.4 MB；combo 9,291 页）。
- `.tmp/dist-combo/_verify/{static_check.py, dom.test.mjs, http_check.mjs, smoke_combo.py, probe_*.py}`。
- `reports/combo-page-integration.md`：本报告。
