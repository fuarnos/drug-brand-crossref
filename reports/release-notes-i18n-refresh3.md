# What's new 补译文 v0.6.0–v0.8.2（task-117）

> 日期：2026-10-29 ｜ 对象：`data/release_notes_i18n.json`
> 产物：更新后的 `data/release_notes_i18n.json`（**37 版本 / 146 条**）· 本报告 · `.tmp/release-notes3/`（构建脚本、校验、更新前备份）
> 边界：**未改 `site/build.py`、未写 `data/drugs.db`、未 git/发布**；只更新数据文件与报告。

---

## 1. 结论

| 指标 | 更新前 | 更新后 |
|---|---:|---:|
| 覆盖版本 | 24（v0.5.5 → v0.1.0） | **37（v0.8.2 → v0.1.0）** |
| 条目总数 | 95 | **146（+51）** |
| 新增版本 | — | **13**：v0.5.6、v0.6.0、v0.6.1、v0.6.2、v0.6.3、v0.6.4、v0.6.5、v0.6.7、v0.7.0、v0.7.1、v0.8.0、v0.8.1、**v0.8.2（占位）** |
| 三语数组等长 | ✅ | ✅ 146 / 146 / 146 |
| 空值 | 0 | **0** |
| `machine_translated` | 全 true | 全 true |
| 旧 24 版本内容 | — | **逐字段未变** |

- **What's new 不再出现「译文待补」**：v0.6.0–v0.8.1 全部有 zh/en/es 三语块；v0.8.2 为发布说明草拟的**占位**（CHANGELOG 尚未定稿，见 §4）。
- 本次**额外补了 v0.5.6**：任务列表只列 v0.6.0–v0.8.2，但 JSON 实际缺 v0.5.6（也显示「译文待补」），按同一规则补齐（5 条）。
- **zh-Hant 附加块**：用 task-53 的 OpenCC + 台湾术语流水线把 zh 转成 zh-Hant（37 版全有）。**注意：`site/build.py` 的 What's new 目前只渲染 `zh/en/es` 三块，zh-Hant 字段为未来接入预留、暂未被消费**。

---

## 2. 新增版本明细

| 版本 | 条数 | 主题 |
|---|---:|---|
| v0.5.6 | 5 | A1 产品详情懒加载、A3 盐型/释放徽章、B6/B7 行级报告+复制/CSV、What's new 修复、站点体积 |
| v0.6.0 | 3 | 组合页跨市场同组合区块（exact/overlap/none/unmatched）、映射口径、combo.cross_* 9 键 |
| v0.6.1 | 3 | 停写 55 MB index.json（dist −54.9 MB）、core 加剂型字段、旧缓存兼容 |
| v0.6.2 | 3 | zh-Hant UI（247 键/5 页/hreflang）、繁→简检索 2,966 字对、三语不回归 |
| v0.6.3 | 3 | U1 首屏三步引导、U2 各国叫法横排、U3 界面标签本地化 |
| v0.6.4 | 4 | ATC 码搜索、/glossary 13 术语×4 语、键盘快捷键、索引 ATC 字段 |
| v0.6.5 | 4 | EN/ES 去中文残留、首页示例按语言、首搜提示 ~0.2 MB、四语 328 键 |
| v0.6.7 | 5 | 多国矩阵、语言优先列序、/warn 分页、四语 336 键、增量发布 |
| v0.7.0 | 5 | 台湾 TFDA 16,457 产品、zh-Hant 全站、TFDA/OGDL 署名、TW 规格解析提示、站点数字 |
| v0.7.1 | 3 | ATC 类别浏览 1,154 页 + 16 大类、四语类名/搜索、L2–L4 译名待校订 |
| v0.8.0 | 5 | 新加坡 HSA 5,511 产品、9 市场矩阵全显、HSA/SODL 署名、在册≠在售、站点数字 |
| v0.8.1 | 3 | 双语对照（zh 536/es 640、来源徽章、版本 v2026-10-28.1）、显示原文开关、站点数字 |
| **v0.8.2（占位）** | 5 | 零结果埋点 search0-*（去重/防抖/≤64 字）+ About 四语隐私说明 + search-weekly 周报；ATC 大类四语显示名修复；首页三步引导卡上移；搜索后收起「按大类浏览」；页头导航/语言切换换行修复 |
| **合计** | **51** | |

---

## 3. 校验（`validation.json`）

| # | 校验项 | 结果 |
|---|---|---|
| 1 | JSON 可解析（UTF-8） | ✅ |
| 2 | 版本顺序 = CHANGELOG 倒序（v0.8.2 占位放最前） | ✅ |
| 3 | 三语数组等长（zh/en/es） | ✅ 146/146/146 |
| 4 | 无空值 | ✅ 0 |
| 5 | `machine_translated` 全 true | ✅ |
| 6 | 旧 24 版本逐字段未变 | ✅ `old_versions_unchanged=true` |
| 7 | 新增版本/条数与 CHANGELOG 对齐 | ✅ +13 版 / +51 条 |
| 8 | `_meta.versions=37`、`_meta.items=146`、`generated_at` 更新 | ✅ |
| 9 | 与 build.py `build_whats_new()` 兼容（非 `_meta` 的每版 dict + zh/en/es 数组） | ✅ |
| 10 | zh-Hant 附加块生成 | ✅（37 版；build.py 暂未消费，见 §4） |

明细：`.tmp/release-notes3/validation.json`；更新前备份：`.tmp/release-notes3/release_notes_i18n.before3.json`。

---

## 4. 剩余缺口与注意

1. **v0.8.2 仍是占位**：CHANGELOG 尚无 v0.8.2 节，本文件的 v0.8.2 条目按发布说明草拟，`provisional: true`。**发布经理写定 CHANGELOG v0.8.2 后需按最终条目重新生成/核对**（脚本 `.tmp/release-notes3/build_refresh3.py`，或在 review 时直接按 CHANGELOG 调整数组）。
2. **zh-Hant 未被 build.py 消费**：`build_whats_new()` 只渲染 `zh/en/es` 三块；zh-Hant 字段已生成、待后续 build 接入（接入时无需改数据结构）。因此繁体界面用户当前看到的 What's new 仍是三块中的中文块（与 v0.6.2 以来行为一致）。
3. **AI 译文未经人工审校**：`machine_translated=true` 不变；用户可见的 What's new 标注「AI 翻译，中文原文为准」。
4. **v0.5.6 不在任务清单但已补**：JSON 原缺该版，本轮一并补齐；若发布/验收口径不希望包含，可单独回退该版（数据旧版备份在 `.tmp/release-notes3/`）。
5. **版本数口径**：release_notes JSON 覆盖 CHANGELOG 全部 **36 个已发布版本 + v0.8.2 占位 = 37**；与站点「17 版」发布计数不是同一口径（后者是本次谷段的发布版本数）。

---

## 5. 复现与产物

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 备份 + 生成 + 校验 + 写回（v0.8.2 占位随脚本内置）
& $py .tmp\release-notes3\build_refresh3.py
```

| 产物 | 内容 |
|---|---|
| `data/release_notes_i18n.json` | 37 版本 / 146 条：zh（CHANGELOG 权威）+ en/es（AI 译文）+ zh-Hant（预留） |
| `.tmp/release-notes3/build_refresh3.py` | 生成/校验脚本（复用 task-53 OpenCC 流水线） |
| `.tmp/release-notes3/release_notes_i18n.before3.json` | 更新前备份（24 版本/95 条） |
| `.tmp/release-notes3/validation.json` | 校验结果 |

边界：只改 `data/release_notes_i18n.json` 与新增报告；**未改 `site/build.py`、`data/drugs.db`，未跑 git/发布**。本文件已可在 v0.8.2 构建前供发布经理使用。
