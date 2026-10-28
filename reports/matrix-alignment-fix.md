# v0.8.2 矩阵列错位排查 + 当地注册名标注报告（task-136）

> 任务：task-136（`site/build.py` 独占，构建 `.tmp/dist-matrix-fix`）。
> 用户截图：CA 列出现中文「欧双宁」，疑似矩阵行列错位。未改 `data/*`、tests、`site/dist`。

## 0. 根因与修复

**根因（confirmed）**：成分页矩阵 **tbody 的 `<td>` 没有 `data-country` 属性**，而 i18n.js 按界面语言重排矩阵时只按 `data-country` 排序单元格；表头 `<th>` 有属性会被重排，**行内 td 没有属性保持原序 → 表头与整行数据错位**，导致 CA 列位置显示成 CN 的中文品牌名（欧双宁）。

| 修复 | 详情 |
|---|---|
| 行单元格固定 N 个 | 每行都输出「1 个规格 td + len(countries) 个国家 td」，**无数据也显式输出 `<td data-country>` + 本地化「未收录」**，不再跳过 |
| 国家属性对齐 | 所有国家 td（含空列）都带 `data-country`，i18n.js 重排后行/表头逐列一致 |
| 当地注册名标注 | 矩阵下方新增 `data-i18n="matrix.brand_note"`：各国列显示当地注册商品名，不是翻译（四语） |
| CN 英文原名 | 若 CN 中文注册名在 DB 中存在同 key 拉丁写法，则在其下方显示 `.m-en` 小字（如 欧双宁 · Jentadueto）；当前 DB 中 CN 中文 trade key 无拉丁 variant（仅 `欧双宁`），故小字暂不出现——数据侧补 Latin 别名后自动显示，不造数据 |
| 表头/首列 | 表头保留 ATC 国家码 + 首列「规格 / 剂型 / 释放」；品牌标注说明当地注册名未翻译 |

## 1. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-matrix-fix'; & $py -X utf8 site/build.py   # exit 0, 476.0 MB
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-matrix-fix' '<repo>'  # 9/9 PASS
# 临时 http.server 8817 + headless.mjs → ALL CHECKS PASSED
```

- **静态 9/9**：抽样 80 页矩阵**每行 td 数 = 表头国家数 + 1**、每行 `data-country` 顺序与表头完全一致、**CA 列无中文**、空国 `matrix.none` 抽样存在、品牌标注 key 四语、`.m-en` 样式、无 0 字节。
- **Headless（Chrome CDP）**：zh 矩阵 120 行、表头 `CN,TW,SG,US,GB,CA,AU,ES,MX`，**每行逐列对齐**；CA 列 118 个空列显示「未收录」且**无中文**；en 同理（表头 `US,GB,CA,AU,SG,CN,ES,MX,TW`）；四语品牌名标注可见；移动端 390px 页面不溢出、矩阵内部横滚、9 列全显示。
- **回归**：无数据国家 td 显式输出；多品牌/`+N`/长名均在同一 td 内，不再影响列数。

## 2. 风险 / 已知事项

1. **CN 英文原名小字**：DB 中 CN 中文注册名目前无同 key 拉丁 variant（0 条），故「欧双宁 · Jentadueto」式小字暂不显示；补齐 `name_variant`（Latin 别名）后自动显示。
2. 错位根因是前端排序属性缺失，修复后所有语言（zh/zh-Hant/es/en）列一致。
3. 矩阵行数上限仍 120；空行（所有国家都未收录）已在更早版本隐藏（builder 只生成有数据的 spec 行）。
4. 当前矩阵列数按全部 9 市场输出（v0.8.0 决策，移动端横滚）。

## 3. 回滚

`git checkout -- site/build.py` 后重建；或仅回退 td `data-country`/空 td/标注/`.m-en` 改动。

## 4. 产物

- `.tmp/dist-matrix-fix/`（62,880 文件 / 476.0 MB）。
- 验收脚本：`static_check.py`、`headless.mjs`（TEMP `matrix-fix-verify-20261028/`）。
- `reports/matrix-alignment-fix.md`：本报告。
