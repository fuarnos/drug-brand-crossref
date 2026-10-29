# task-28：AU ARTG 数据展示（代码完成，构建待 v0.9.1）

> 2026-10-30 ｜ `site/build.py`、`README.md` ｜ 未写 DB、未构建、未 publish。
> 前置：AU ARTG Medicines 2026-10-28 已入库（DB 477,098 / AU 44,794 / 419.6 MB；`status='unknown'` 新增 32,904）。

## 0. 结论

- About 四语新增 AU 署名：**TGA ARTG Medicines 2026-10-28 / 数据截止 2026-10-28 / 无注册状态列、状态一律未确认 / 在册≠在售**；不写授权措辞。
- 无成分产品（**3,911** 全库：AU 1,495 / US 2,229 / MX 121 / SG 66）在结果、名字页、厂家页显示「**成分未收录（名称层）**」角标；不链成分页。
- **Export Only**：2,632 个（新增 ARTG 2,278 + 既有 354，按 `note/category` 识别）；结果行与明细加「**仅供出口 / Export Only**」四语徽章，与 `unknown` 状态并存。
- AU `status='unknown'` 不再整批跳过：矩阵显示 AU 列并加 `matrix.au_note`（导出无状态列、在册≠在售）。
- 计数：README 更新为 **477,098 总产品 / AU 44,794 / 10 市场**；About 覆盖表/统计为构建期动态，自动取 DB 当前值。
- 验收：py_compile 通过；索引含 195,553 条（含名称层）；无成分名字页/厂家页角标、Export Only JSON 2,632、About AU 行+署名、orlistat AU 列冒烟通过。

## 1. 数据口径（只读实测）

| 项 | 数值 |
|---|---:|
| 全库产品 | 477,098 |
| AU 产品 | 44,794（PBS 5,452 + CMI 4,730 + ARTG 明细 1,559 + 补全 144 + ARTG 2026-10-28 32,904 + 人工 5） |
| AU status | active 7,160 / unknown 37,634（ARTG 新 32,904 全 unknown） |
| 全库无成分产品 | 3,911（AU 1,495 / US 2,229 / MX 121 / SG 66） |
| Export Only | 2,632（新 2,278 + 既有 354） |
| AU 数据截止 | 2026-10-28（TGA ARTG Medicines） |

## 2. 改动

| 位置 | 改动 |
|---|---|
| `load_index` | `LEFT JOIN product_component/variant/substance`，无成分产品也进检索索引；新增 `nc`（名称层）、`eo`（Export Only）标记；`v=""`、不链成分 |
| 结果 JS | `ingredientHTML`：`nc=1` → 「成分未收录（名称层）」角标；结果行加 Export Only 徽章 |
| 明细 | 新增 `data/export-only.json`（2,632 PID）懒加载；明细品牌列加 Export Only 徽章，状态 unknown 并存 |
| 名字页 | `collect_name_data` LEFT JOIN；无成分页显示同一角标；单包装产品表 LEFT JOIN，标注 Export Only；无成分 trade 名不受 44k 体积守卫限制（保证 3,911 名称层可点） |
| 厂家页 | 无成分产品成分列改为「成分未收录（名称层）」角标，不链成分页 |
| 矩阵 | AU/HK 的 unknown 记录不跳过；`matrix.au_note` 四语；`matrix.hidden_note` 说明 HK/AU 例外 |
| About | 新增 `about.au_source` 四语（TGA ARTG Medicines 2026-10-28 / 2026-10-28 / 无状态列 / 在册≠在售 / 3,911 名称层） |
| README | 10 市场、AU 44,794、HK 13,935、477,098；AU 来源拆分含 ARTG 2026-10-28 |

## 3. 冒烟证据

```text
no-component entry ELEVIDYS: t=1 nc=1 v="" u=elevidys.html m=Sarepta...
name page: ingredient.unrecorded=True
maker page: ingredient.unrecorded=True
export-only.json: 2,632 IDs（AU-ARTG-100187…）
About AU row: <td>AU</td> True；about.au_source True
orlistat: data-country="AU" True；matrix.au_note True
i18n en/es/zh/zh-Hant：ingredient.unrecorded / badge.export_only / about.au_source / matrix.au_note / matrix.hidden_note 全 True
```

## 4. 待办

- 全量构建后抽查 AU 结果行 Export Only、无成分角标、名字页/厂家页、sitemap 不暴涨。
- 正式构建（`site/dist`，2026-10-30）：**110,200 文件 / 882.6 MiB / sitemap 60,737**；0 空文件；页脚 v0.9.1。相对 v0.9.0（116,883 / 770.8 MiB / 68,430）体积仍在 900MiB 目标内。详见 `reports/v091-size-strategy.md`。
- 3,911 名称层产品无成分是数据边界（ARTG 1,446 仅名称 + 49 成分无法解析 + 既有 2,416）；不补猜、不伪造成分。
- HK/AU 的 status unknown 是数据源限制（HK 无状态列、ARTG 导出无状态列），页面已明示。
- Lighthouse/WCAG/UX P0 与本次同批构建，见 `lighthouse-optimization.md` / `ux-fixes.md`。
