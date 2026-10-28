# v0.8.4 显示层修复报告（task-128）

> 任务：task-128（`site/build.py` 独占，构建 `.tmp/dist-display`）。未改 `data/*`、tests、`site/dist`。
> 用户「不符合直觉」问题：重复剂型、异常规格、长品牌名、状态/空值语义、CN 拉丁名无中文。

## 0. 结果

| 项 | 结果 |
|---|---|
| ① 通用名+剂型去重 | 矩阵品牌显示与客户端结果品牌名：当名称尾部已含剂型词（胶囊/片/注射液/胶囊…或 tablet/capsule…）时剥离重复剂型（如「阿莫西林胶囊」+ row「胶囊」→ 显示「阿莫西林」）；**title 保留全名**；未知长尾不强行剥离 |
| ② 异常规格防护 | `_strength_suspect()`：数值 ≥1,000,000 或 >10,000 且单位非 u/iu/unit/%/ml（如 2,081,980 mg、400064 g）→ 行加 `data-suspect="1"`、规格列显示「**规格待核**」角标、排序置最后（仅标记，**不删数据**） |
| ③ 长名截断 + 状态角标 | 矩阵品牌 `.m-brand` 两行截断（`-webkit-line-clamp:2`）+ title 全名；客户端品牌名同样 title 全名。状态：A1 明细状态列改为彩色角标 `st-active/st-discontinued/st-withdrawn/st-unknown` |
| ④ 空值语义 | 矩阵空单元格「未收录（not recorded）」与规格「未公开（not disclosed）」文案保持区分；品牌标注仍为「当地注册商品名，不是翻译」 |
| ⑤ CN 拉丁商品名+中文小字 | CN 列若品牌为拉丁名且成分有 `inn_zh`，品牌下方显示 `.m-zh` 中文通用名小字（如 `PLASBUMIN-20` + 人血白蛋白）；品牌名本身不翻译 |
| 四语 | `matrix.spec_check` 四语；I18N **388 keys ×4 一致** |
| 构建 | exit 0；62,217 文件 / **472.5 MB**；sitemap 62,057；drug 12,447 / name 31,134 / combo 10,284 |

## 1. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-display'; & $py -X utf8 site/build.py   # exit 0, 472.5 MB
& $node --check .tmp\dist-display\assets\app.js                     # 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-display' '<repo>'  # 12/12 PASS
# 临时 http.server 8820 + headless.mjs → ALL CHECKS PASSED
```

- **静态 12/12**：存在 `data-suspect=1` 行且排最后；品牌 title 全名；CSS 两行截断；`matrix.spec_check` 四语；`.m-zh` 样式与实例；状态 4 类 CSS；客户端去重+title；无 0 字节。
- **Headless（Chrome CDP）**：loratadine 品牌 title 全名（含非翻译注）、高度 ≤2 行（38px）、矩阵 9 列；可疑规格页 `allogeneic-thymocyte…` 行标记 + 排最后 + 「规格待核」角标；`albumin-human` CN 列显示中文小字「人血白蛋白」；搜索结果 A1 明细展开 12 个彩色状态角标（st-active 等）；metformin 9 列 `CN,TW,SG,US,GB,CA,AU,ES,MX`。
- **回归**：四语 keys 一致、矩阵已对齐（task-136）、无 0 字节。

## 2. 风险 / 已知事项

1. **异常规格**为启发式：单位 u/iu/unit/%/ml 的数值不判可疑；不删除数据，仅标记 + 排后，待数据清洗（task-129）处理。
2. **去重**只在能识别剂型后缀时生效；长尾/非常见剂型词不强行剥离，避免误删名称。
3. **CN 中文小字**只在成分有 `inn_zh` 且品牌为拉丁名时出现；没有则不显示，不造译名。
4. **状态角标**主要出现在搜索结果 A1 明细（成分页默认只列 active）；如需在更多页面显示状态可后续扩展。
5. 长名两行截断依赖 `-webkit-line-clamp`（现代 Chrome/Edge/Safari/Firefox 支持）；title 保留全名。

## 3. 回滚

`git checkout -- site/build.py` 后重建；或仅回退 `_strength_suspect`/`_strip_form_from_label`/矩阵渲染/CSS/客户端 brandHTML 改动。

## 4. 产物

- `.tmp/dist-display/`（62,217 文件 / 472.5 MB）。
- 验收脚本：TEMP `display-verify-20261028/`。
- `reports/display-fixes-impl.md`：本报告。
