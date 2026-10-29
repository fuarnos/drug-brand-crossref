# task-19：无商品名产品显示「无商品名」+ 厂家（代码完成，构建待 DB 窗口）

> 2026-10-29 ｜ `site/build.py` ｜ 未写 DB、未改数据、未构建。

## 0. 结论

- 结果行 / 成分页矩阵 / 名字页：无 trade 名的产品在商品名位置只显示「**无商品名**」纯文本角标（`st-badge st-unknown brand-none`），**不链接、不放厂家**；可附通用名+剂型小字。
- 有 trade 名照旧显示品牌（不翻译）。
- 厂家：结果行 `maker` 列/矩阵明细/产品明细使用厂家页链接；商品名位置不出现厂家链接。
- 实测：active 产品中 **219,138 个无 trade 名**，涉及 **4,325 个成分**；imiquimod 成分页矩阵冒烟出现 4 处 `brand.none` 占位。

## 1. 改动

| 位置 | 改动 |
|---|---|
| 索引 `load_index` | 每条 entry 增加 `t: 1/0`（1=trade 名，0=只有通用名） |
| 结果 JS `brandHTML` | `t!==1` → 「无商品名」纯文本 + `e.x`/剂型说明；不生成 name 链接 |
| 结果明细 `detPanelHTML` | 新增 Brand 列；空 brand → 「无商品名」 |
| 成分页矩阵 | 无 trade 名的产品在对应国家 cell 加 `brand.none` 占位，不静默消失 |
| 名字页 | 通用名页标题下加「无商品名」角标；单包装 trade 页仍显示品牌 |
| 四语 | `brand.none`：No trade name / Sin nombre comercial / 无商品名 / 無商品名 |

## 2. 复核

```powershell
& $py .tmp/cat2/task19_matrix_smoke.py   # 12,447 drug 页写 .tmp；imiquimod 矩阵 brand.none=True
& $py .tmp/cat2/v09_code_check.py        # 四语 key / 无 trade 条目 29,085
```

## 3. 缺口 / 待办

- 全量构建后抽查 CN 无 trade 名结果行：商品名位置不可点、厂家列可点进 maker 页（依赖 task-20 全量厂家页）。
- 名字页产品级表格只对单包装页生成（task-6），多包装名字页保持原卡片聚合。
