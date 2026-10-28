# Release notes 译文补齐 v0.5.2–v0.5.5（task-64）

> 日期：2026-10-28 ｜ 对象：`data/release_notes_i18n.json`
> 产物：更新后的 `data/release_notes_i18n.json`（24 版本 / 95 条）· 本报告 · `.tmp/release-notes/`（构建脚本、变更前备份、校验明细）
> 边界：**未改 `site/build.py`、未写 `data/drugs.db`、未跑 git/发布**；只更新数据文件与报告。

---

## 1. 结论

| 指标 | 更新前 | 更新后 |
|---|---:|---:|
| 覆盖版本 | 21（v0.5.2 → v0.1.0） | **24（v0.5.5 → v0.1.0）** |
| 条目总数 | 86 | **95（+9）** |
| 文件体积 | 62,828 B | 70,948 B |
| 三语数组等长 | ✅ | ✅ 95 / 95 / 95 |
| 空值 | 0 | **0** |
| `machine_translated` | 全 true | 全 true |

- **任务要求的 4 个版本（v0.5.2–v0.5.5）现在全部在 JSON 中**：
  - **新增 3 个版本 / 9 条**：v0.5.5（4 条）、v0.5.4（2 条）、v0.5.3（3 条）；
  - **v0.5.2 在旧 JSON 中已存在（1 条）**：中文与当前 `CHANGELOG.md` 逐字一致、en/es 齐全，本轮复核通过、保持原样（不重复翻译、不重复插入）。
- **旧 21 个版本内容逐字节未变**（除 `_meta` 的 `versions/items/generated_at` 更新）。
- **与 build.py v0.5.6 的消费逻辑兼容**：`build_whats_new()` 以 CHANGELOG 为版本主列表、用本 JSON 的 `zh/en/es` 数组渲染语言块；补全后 **24 个版本全部有译文，页面不再出现「译文待补」占位**。

---

## 2. 新增内容摘要（中文逐条取自 CHANGELOG，en/es 为 AI 机器翻译）

| 版本 | 条数 | 主题 |
|---|---:|---|
| **v0.5.5** | 4 | 中文界面显示中文成分名（索引 `xz` 数组 65,075 条）；页面元信息三语（title/description/OG/canonical/hreflang，新增 `/es/`、`/zh/` 静态副本）；What's new 三语渲染（标注「AI 翻译，中文原文为准」）；跨市场身份合并 141 个成分（12,790→12,649）+ DB VACUUM 450→325 MB |
| **v0.5.4** | 2 | 新增厂家页约 7,000 个（MAH，≥5 产品）；索引/导航：厂家链接入索引、品牌/成分/厂家三类目标彻底分开、无页目标不可点 |
| **v0.5.3** | 3 | 品牌/成分点击目标修复（不再回退到第一成分页）；新增品牌页 29,140 / 组合页 9,339（站点 30k→约 51k 页）；索引新增 `cu` 组合页字段、88 个抽样链接 0 404 |

字段结构与旧版本完全一致（`date / zh / en / es / machine_translated`），样例如下：

```json
"v0.5.3": {
  "date": "2026-10-29",
  "zh": ["**品牌/成分点击目标修复**：……"],
  "en": ["**Brand/ingredient click targets fixed**: ……"],
  "es": ["**Destinos de clic de marca/principio corregidos**: ……"],
  "machine_translated": true
}
```

---

## 3. 翻译口径

1. **中文为权威**：`zh` 数组由脚本重新解析 `CHANGELOG.md` 得到（与手抄对照，未改写原文）。
2. **en/es 为 AI 机器翻译**：逐条翻译，保留关键数字（65,075 / 7,000 / 29,140 / 9,339 / 37,514 / 141 / 450 MB → 325 MB…）、路径（`data/release_notes_i18n.json`、`/es/`、`/zh/`）、代码/字段名（`xz`、`cu`、core.json）与机构名；西语用 `≥`、`«»`、`0 404` 等与站点既有西语风格一致。
3. **不译**：CHANGELOG 版本号/日期、代码标识、英文监管/技术名词（MAH、OG、SEO、hreflang、core.json）原样保留。
4. **不重译 v0.5.2**：旧译文（task-43 产出）与当前中文一致，按"已覆盖"处理。

---

## 4. 校验（脚本 `build_update.py` 内置，校验失败不写文件）

| # | 校验项 | 结果 |
|---|---|---|
| 1 | JSON 可解析（UTF-8） | ✅ |
| 2 | 版本倒序与 CHANGELOG 完全一致 | ✅ 24 版：v0.5.5 → v0.1.0 |
| 3 | 每版本 `len(zh)==len(en)==len(es)` | ✅ 95/95/95 |
| 4 | 三语数组无空字符串 | ✅ 0 |
| 5 | 版本日期与 CHANGELOG 一致 | ✅ |
| 6 | 旧 21 个版本对象（除 `_meta`）逐字节不变 | ✅ `old_versions_unchanged=true` |
| 7 | 新增翻译条数/版本与 CHANGELOG 对齐 | ✅ +3 版 / +9 条 |
| 8 | `machine_translated` 全 true | ✅ |
| 9 | `_meta.versions=24`、`_meta.items=95`、`generated_at` 更新 | ✅ |
| 10 | 与 build.py v0.5.6 `build_whats_new()` 消费逻辑兼容（非 `_meta` 的每版本 dict、zh/en/es 数组） | ✅（逻辑模拟通过） |

明细：`.tmp/release-notes/validation.json`；变更前备份：`.tmp/release-notes/release_notes_i18n.before.json`（可 diff 复核）。

---

## 5. 风险与后续

1. **AI 译文未经人工审校**：`machine_translated=true` 保持不变；发布前建议人工抽 2 个版本（v0.5.5 / v0.5.3）核对数字与机构表述。
2. **构建/发布不在本任务**：JSON 已就绪，`site/build.py`（v0.5.6 逻辑）下次 rebuild 即会渲染 24 个版本的三语块；建议验收：
   - `/whats-new.html` 英文 = 24 个版本、无「译文待补」；
   - `?lang=es` / 西语入口切到 What's new 时显示西语条目；
   - 版本数/最新版本仍与页脚一致（v0.5.5）。
3. **流程化建议**：以后每次发版把本脚本（`.tmp/release-notes/build_update.py`，仅改 `NEW_TRANS` + 重跑）作为发布前步骤：**CHANGELOG 定稿 → 解析 → 补 en/es → 自动校验（顺序/长度/空值/旧版不变）→ build**；可把校验并入发布守则。
4. **文件权限**：本文件是数据文件，接入方（build.py）只读；不要手工改中文数组（应以 CHANGELOG 为源重新生成）。

---

## 6. 复现与产物

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 1) 备份当前 JSON（已做）
Copy-Item data\release_notes_i18n.json .tmp\release-notes\release_notes_i18n.before.json
# 2) 补译 + 校验 + 写回（脚本内含 CHANGELOG 解析与 10 项校验）
& $py .tmp\release-notes\build_update.py
# 3) 复核
& $py .tmp\release-notes\verify.py
```

| 产物 | 内容 |
|---|---|
| `data/release_notes_i18n.json` | 24 版本 / 95 条 ×（zh 权威 / en / es 机器翻译） |
| `.tmp/release-notes/build_update.py` | 补译 + 校验 + 写回脚本（下版只改 `NEW_TRANS`） |
| `.tmp/release-notes/release_notes_i18n.before.json` | 更新前备份（diff/回退用） |
| `.tmp/release-notes/validation.json` | 校验结果 |
| `.tmp/release-notes/verify.py` / `show_changelog.py` | 复核脚本 |

边界：只改 `data/release_notes_i18n.json` 与新增报告；**未改 `site/build.py`、`data/drugs.db`，未跑 git/发布**。
