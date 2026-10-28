# CN 中文成分名补齐 v2（236 个缺 inn_zh 成分 + 旧回填复核）— task-127

> 日期：2026-10-28 ｜ 只读 `data/drugs.db`（未写库）、未改 `site/build.py`、未 git/发布。
> 产物：`data/inn_zh_backfill_v2.csv`（236 fill + 22 correction = 258 行）、`etl/build_inn_zh_backfill.py --v2`、本报告；
> SQL 草案/统计在 `.tmp/inn-zh2/`（`fill.sql`、`corrections.sql`、`v2_stats.json`、`old_suspicious.txt`）。

## 1. 结论摘要

| 指标 | 结果 |
|---|---:|
| 目标缺 `inn_zh` 成分 | **236** |
| 本次补齐（带中文名） | **236（100%）**：`high 196 / medium 40`，`keep_empty 0` |
| 覆盖 CN 产品 | **31,080 → 0**（CN 产品英文通用名显示比例 **21.2% → 0%**） |
| 保守口径（剔除 14 个“产品映射可疑”成分） | 影响产品 **155/146,347 = 0.106%** → **仍远低于目标 <5%** |
| 旧回填 CSV 复核 | 898 行（复核时）→ **23 条可疑**；**22 条修正**（9 条 DB 已应用 → UPDATE 草案；13 条仅 CSV 值） |
| apply 后 DB `inn_zh` | 2,879 → **3,115**（+236）；CN 使用的 3,065 个成分全部有中文名 |
| 旧回填 CSV 恢复 | 已从 **git HEAD** 恢复：899 行（表头+898）、sha256 `ddbe2c959ddf7149…`、`git status` clean；23/23 可疑对照匹配 |

> **目标达成**：英文通用名比例 0%（保守 0.106% < 5%）。

## 2. 236 个成分：来源、证据、置信度

### 2.1 命名依据

- **中国药典/INN 中文名** 为主（人工核对；如 Glucose→葡萄糖、Sodium Chloride→氯化钠、Levofloxacin→左氧氟沙星、Aspirin→阿司匹林、Ascorbic Acid→维生素C）；
- **NHSA「医保药品分类与代码」注册名**（`data/raw/nhsa/` 快照）作为**产品名证据**：每个成分列出该成分单成分 CN 产品的前 3 个注册名 + 产品数，例如：
  - `glucose`：`葡萄糖注射液(4324)；葡萄糖氯化钠注射液(2123)；口服五维葡萄糖(65)` → 葡萄糖
  - `levofloxacin`：`盐酸左氧氟沙星片(300)；盐酸左氧氟沙星胶囊(294)；乳酸左氧氟沙星氯化钠注射液(246)` → 左氧氟沙星
  - `aspirin`：`阿司匹林肠溶片(465)；复方乙酰水杨酸片(158)；注射用赖氨匹林(103)` → 阿司匹林
  - `pyridoxine`：`维生素B6注射液(352)；维生素B6片(345)` → 维生素B6
- `source_url` 统一为 NHSA 公开页：https://code.nhsa.gov.cn/yp/toPublicGoodsData.html （事实字段/注册名出处；药典名人工核对）。

### 2.2 置信度口径

| confidence | 条数 | 口径 |
|---|---:|---|
| high | 196 | 人工/药典中文名命中该成分 CN 单成分产品名（或产品名以之开头） |
| medium | 40 | 官方中文名已知，但产品名不含该名（生物制品/疫苗/复方成分/映射可疑），或只有组合产品证据 |
| 空（keep_empty） | 0 | 本轮 236 个均有可确定官方名 |

抽样（high）：葡萄糖(6,559 产品)、氯化钠(2,819)、左氧氟沙星(1,871)、维生素C(1,575)、红霉素(1,033)、阿司匹林(1,025)、双氯芬酸(972)、头孢呋辛(750)、维生素B6(729)、维生素B1(662)、替米沙坦(592)、氨苄西林(583)…
抽样（medium）：克拉维酸(311)、曲安西龙(301)、磷酸钙(152)、非格司亭(136)、阿地白介素(62)、锝[99mTc]亚甲基二膦酸盐(52)、地诺前列酮(41，映射可疑)…

### 2.3 映射可疑（14 个，已填官方名但需复核产品映射）

`dinoprostona`(41 产品，产品名多为卡前列素/米索前列醇)、`carbenoxolona`(32)、`otilonio`(31)、`clomifeno`(16，产品名重组人促卵泡激素)、`bromelaina`(7)、`acido-mefenamico`(6)、`colistimethate`(5)、`periciazina`(4)、`parafina-liquida`(4)、`benzbromarona`(4)、`panobinostat`(2)、`vernakalant`(1)、`setmelanotida`(1)、`butilescoprolamina`(1) —— 官方中文名与库内 CN 产品名不一致，说明 **substance↔CN 产品的成分映射可能错**，不是名字缺失；建议另起一次映射审计（本任务只标 note，不硬改映射）。

## 3. 旧回填 CSV（`data/inn_zh_backfill.csv`）复核

### 3.1 检测规则

对 898 行逐行检查：
1. `zh_candidate` 与 CN `trade` 名同形且不是该成分的 CN `inn` 名 → **疑似品牌名误当通用名**；
2. 含剂型词/厂家词/噪声词/字母数字、长度异常；
3. 与 DB 当前 `substance.inn_zh` 不一致（判断是否已应用）。

结果：**23 条可疑**（完整清单 `.tmp/inn-zh2/old_suspicious.txt`）。

### 3.2 修正清单（22 条；1 条误报保留）

| substance | 旧值（错） | 新值（正确） | 状态 |
|---|---|---|---|
| dextran-70 | 润齐 | 右旋糖酐70 | **DB 已应用 → UPDATE** |
| dopamine | 阿斯克丁 | 多巴胺 | **DB 已应用 → UPDATE** |
| goserelin | 诺雷得 | 戈舍瑞林 | **DB 已应用 → UPDATE** |
| methylphenidate | 专注达 | 哌甲酯 | **DB 已应用 → UPDATE** |
| calcium-gluconate | 弘泰 | 葡萄糖酸钙 | **DB 已应用 → UPDATE** |
| fluoxetine | 百优解 | 氟西汀 | **DB 已应用 → UPDATE** |
| paroxetine | 乐友 | 帕罗西汀 | **DB 已应用 → UPDATE** |
| tretinoin | 艾力可 | 维A酸 | **DB 已应用 → UPDATE** |
| vacuna-anti-neumococo | 纽莫法 | 肺炎球菌疫苗 | **DB 已应用 → UPDATE** |
| alglucosidase-alfa | 美而赞 | 阿糖苷酶α | 仅旧 CSV（非 DB） |
| aminocaproic-acid | 凯乃银 | 氨基己酸 | 仅旧 CSV |
| amphotericin-b | 锋克松 | 两性霉素B | 仅旧 CSV |
| clomifene | 法地兰 | 氯米芬 | 仅旧 CSV |
| dextran-40 | 福他乐 | 右旋糖酐40 | 仅旧 CSV |
| fludeoxyglucose-f-18 | 弗唐派特 | 氟[18F]脱氧葡糖 | 仅旧 CSV |
| leuprorelin | 抑那通 | 亮丙瑞林 | 仅旧 CSV |
| magnesium-gluconate | 包乐 | 葡萄糖酸镁 | 仅旧 CSV |
| sodium-chloride | 乐敦清 | 氯化钠 | 仅旧 CSV |
| strontium-chloride | 思通宁 | 氯化锶[89Sr] | 仅旧 CSV |
| sufentanil | 舒芬尼 | 舒芬太尼 | 仅旧 CSV |
| tocopherol | 清之维 | 维生素E | 仅旧 CSV |
| vitamin-b-complex | 水乐维他 | 复合维生素B | 仅旧 CSV |

- **误报保留**：`water-for-injection → 灭菌注射用水` —— 这是官方中文名（含“注射用水”属规范名），不是品牌，保留。
- **✅ 数据操作事故已恢复（2026-10-28）**：探查阶段曾误触发 task-42 脚本普通模式、把原 `data/inn_zh_backfill.csv` 重跑覆盖为 50 行。已按 Lead 指示从 **git HEAD 恢复**（`tools\git\cmd\git.exe show HEAD:data/inn_zh_backfill.csv`，blob `1de332c…`，**未做提交**）：**899 行（表头 + 898 数据行）、sha256 `ddbe2c959ddf7149…`、`git status` clean**；与 `old_suspicious.txt` 的 23 条可疑记录逐条对照 **23/23 匹配**；`data/inn_zh_backfill_v2.csv` 未受影响（258 行，sha256 `501145ad…`）。

## 4. 产物与 apply 步骤（窗口执行，本任务不写 DB）

### 4.1 文件

| 文件 | 内容 |
|---|---|
| `data/inn_zh_backfill_v2.csv` | **258 行**：236 fill（substance_id/inn_en/zh_name/confidence/evidence/source_url/affected_products/status/note）+ 22 correction（old_zh/new_zh/db_current_zh/status） |
| `.tmp/inn-zh2/fill.sql` | 236 条 `UPDATE substance SET inn_zh=... WHERE substance_id=... AND (inn_zh IS NULL OR trim(inn_zh)='')`（只填空，不覆盖） |
| `.tmp/inn-zh2/corrections.sql` | 9 条 `UPDATE ... WHERE substance_id=... AND inn_zh='旧品牌名'`（幂等/条件更新，窗口执行） |
| `.tmp/inn-zh2/v2_stats.json` | 统计（236/31,080/0；corrections 22/9 已应用） |
| `.tmp/inn-zh2/old_suspicious.txt` | 旧 CSV 23 条可疑明细 |
| `etl/build_inn_zh_backfill.py` | 新增 `--v2` 模式（只读 DB，可重跑） |

### 4.2 apply 顺序（建议）

1. **备份 DB**（`data/backups/`）；确认无其他写库任务并行。
2. **（推荐先）恢复原 `data/inn_zh_backfill.csv`（898 行）**（git/备份），确认旧值后再执行修正。
3. 执行补齐：`sqlite3` 跑 `.tmp/inn-zh2/fill.sql`（或由 data-depth 的 apply 流程按 CSV 条件更新，幂等）。
4. 执行修正：跑 `.tmp/inn-zh2/corrections.sql`（9 条，均带 `inn_zh='旧值'` 条件；若 DB 已不是旧值则跳过）。
5. 校验：

```sql
-- 期望：0（CN 使用的成分全部有中文名）
SELECT COUNT(DISTINCT v.substance_id) FROM product p
JOIN product_component pc ON pc.product_id=p.product_id
JOIN variant v ON v.variant_id=pc.variant_id JOIN substance s ON s.substance_id=v.substance_id
WHERE p.country='CN' AND (s.inn_zh IS NULL OR trim(s.inn_zh)='');
-- 期望：2,879 -> 3,115
SELECT COUNT(*) FROM substance WHERE inn_zh IS NOT NULL AND trim(inn_zh)<>'';
```

6. 若异常回滚：补齐值可在备份恢复；或对 236 个 sid 执行
   `UPDATE substance SET inn_zh=NULL WHERE substance_id IN (...) AND inn_zh='<本次新值>';`
   修正值可反向 UPDATE 回旧品牌名（仅用于回滚，不建议线上保留）。

## 5. 剩余缺口 / 风险

- **14 个映射可疑成分**（dinoprostona 等 155 产品）：名字已按官方名补，但**成分↔产品映射**存疑；需单独审计（不在本任务范围）。
- **40 个 medium**：生物制品/疫苗/复方成分（克拉维酸、曲安西龙、非格司亭、阿地白介素、锝标记物等），建议人工抽检 10–20 条。
- **旧 CSV 覆盖事故已闭环**：原 898 行文件已从 git HEAD 恢复（899 行含表头、git clean、23/23 可疑对照一致，见 §3.2）；v2 未受影响（258 行）。
- **命名依据限制**：本环境 NMPA 412（WAF）不可访问，本轮官方名以药典/INN 中文名人工核对 + NHSA 注册名证据为准；未逐条引用 NMPA 说明书 URL。
- **其他市场**：本轮只补 CN 使用的成分；非 CN 成分的中文名（如需展示）另议。
- **展示层**：即使数据补齐，展示仍应保留「无中文名时英文回退」逻辑（本任务不改 build.py）。

## 6. 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl/build_inn_zh_backfill.py --v2      # 读 DB -> data/inn_zh_backfill_v2.csv + .tmp/inn-zh2/*.sql
& $python -m py_compile etl/build_inn_zh_backfill.py
```
