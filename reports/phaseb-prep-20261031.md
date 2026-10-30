# Phase B 准备审计（名称清洗 · 只读）

> 执行：2026-10-31 谷段，只读 `mode=ro`；**未改库**。目的：给 v0.9.5 的 task-5 Phase B（CJK 主名 → INN）和「名称清洗」划出精确目标与优先级。
> 数字全部现查（`data/drugs.db`，477,098 产品 / 12,649 成分）。

## 0. 结论

| 事实 | 数字 | 对 Phase B 的含义 |
|---|---|---|
| 成分主名语言 | en **10,858** / zh **1,791** | Phase B 的映射对象就是这 1,791 条 |
| 无中文名（`inn_zh` 空） | **9,534**（75.4%） | 中文界面大量显示英文名；补译名是长期活，不做机器翻译 |
| 有 ATC 但无中文名 | **2,928** | 有 ATC → 可用 ATC 类目名反推中文，是可自动化的第一批 |
| 中文名里带盐/酸根（盐酸/硫酸/马来酸/枸橼酸/钠/钾/铵…） | **633** | 中文名与 base 名口径不一致，检索/对照会错位 → 需清洗规则 |
| 同一中文名指向多个 substance | **15 组** | 检索歧义（甘露醇、氧化锌、曲安西龙、炔诺酮、碘化钾…）→ 逐个确认后保留一条 |
| 名称层无成分产品 | **3,911**（US 2,229 / AU 1,495 / MX 121 / SG 66） | 不在成分对照里，需单独补成分或标注「成分未收录」 |
| CJK 主名且有 ATC（Phase B 优先池） | **1,791** | 全部有 ATC → 可用「ATC 同类 + 盐型 + 唯一候选」规则自动定案一部分 |

## 1. 中文名带盐（633 条）：不是错误，但要统一口径

例：`naltrexone` → 盐酸纳曲酮；`sildenafil` → 枸橼酸西地那非；`verapamil` → 盐酸维拉帕米。
问题不在中文名本身，而在**同一成分的英文是 base、中文是盐**，导致：
- 中文检索「纳曲酮」→ 英文索引 `naltrexone` 对不上盐型写法；
- 跨市场对照时中文名混入盐，与「不可互换」警示的粒度冲突。

**建议（Phase B 同窗口）**：新增 `inn_zh_base`（去掉盐词的中文 base 名）或规则化清洗，只在**展示与检索**层使用；`inn_zh` 原值保留（保留出处）。判不了的计数丢弃。

## 2. 同一中文名 15 组：先确认再动手

已确认的典型：
- **甘露醇**：`Manitol`（CN 320）与 `Mannitol`（GB 23 / AU 16 / US 12）——拼写不同，应保留一条 + 异名表（已进 `data/substance_aliases.csv`）。
- **氧化锌**：`Zinc Oxide`（US 4,544）与另一条（CN 18）——同名不同记录，需按 INN 归一。
- **曲安西龙 / 曲安奈德**：`Triamcinolone` 与 `Triamcinolone Acetonide`——酯型差异，不是同一写法（已在 task-141 的 same_base 里处理，不合并）。
- **炔诺酮**、**碘化钾**、**氯米芬**、**环丙孕酮**、**地喹氯铵**、**多黏菌素E甲磺酸钠** 等：需逐条看是否重复记录。

**动作**：Phase B 里做一次 dry-run 清单（15 组 × 库内产品数 + 来源），确认后合并；合并必须 manifest + 备份。

## 3. 名称层无成分 3,911：别当「缺数据」硬补

- US 2,229 / AU 1,495 多为**只给了名称与厂家**的注册记录（AU 导出无成分列）。
- 页面已标「成分未收录（名称层）」（`reports/no-trade-name-display.md`），保持不变。
- Phase B 不做「猜成分」；只做「按名称精确匹配到已知成分」的尝试，命中才写，不命中计数。

## 4. Phase B 的目标池与规则（沿用既有方案）

- 目标：**1,791 条 CJK 主名 → INN**，全部带 ATC。
- 规则：唯一候选 + ATC 类一致 + 盐型正确才自动定案；判不了丢弃并计数（**不机器翻译**）。
- 数据源优先级（沿用 `task5-inn-mapping-plan.md`）：本地多源（ATC 同类、别名表、CN 注册记录）→ Wikidata（节流，429 时退避）→ 离线 zhwiki。
- 回滚：manifest + 备份 `data/backups/drugs-before-phaseb-YYYYMMDD.db`。
- **不做身份合并**（除 §2 的 15 组重复记录，且单独验收）。

## 5. 复现 SQL（只读）

```sql
-- 主名语言分布
SELECT name_lang, COUNT(*) FROM substance GROUP BY 1 ORDER BY 2 DESC;
-- 无中文名
SELECT COUNT(*) FROM substance WHERE inn_zh IS NULL OR inn_zh='';
-- 有 ATC 无中文名
SELECT COUNT(*) FROM substance WHERE atc IS NOT NULL AND atc<>'' AND (inn_zh IS NULL OR inn_zh='');
-- 中文名带盐
SELECT COUNT(*) FROM substance WHERE inn_zh LIKE '%盐酸%' OR inn_zh LIKE '%硫酸%'
  OR inn_zh LIKE '%马来酸%' OR inn_zh LIKE '%枸橼酸%' OR inn_zh LIKE '%磷酸%' OR inn_zh LIKE '%氢溴酸%'
  OR inn_zh LIKE '%钠%' OR inn_zh LIKE '%钾%' OR inn_zh LIKE '%铵%';
-- 重复中文名
SELECT inn_zh, COUNT(*) n FROM substance WHERE inn_zh IS NOT NULL AND inn_zh<>''
  GROUP BY 1 HAVING n>1 ORDER BY n DESC;
-- 名称层无成分
SELECT country, COUNT(*) FROM product p WHERE NOT EXISTS
  (SELECT 1 FROM product_component pc WHERE pc.product_id=p.product_id) GROUP BY 1 ORDER BY 2 DESC;
```

## 6. 边界

- 只读审计，未改库、未建站、未发版。
- 名称清洗属「展示与检索口径」，不改变产品身份；合并重复记录必须单独验收 + 回滚清单。
- 不翻译、不音译；译名只用有出处的来源。
