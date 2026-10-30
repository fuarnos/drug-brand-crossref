# 同名成分（中文名冲突）15 组：分类与处置

> 2026-10-31 谷段，只读 `mode=ro`。来源 SQL 见 §4。**未改库**。
> 目的：把「同名」拆成三种完全不同的情况，避免 Phase B 一刀切合并。

## 0. 结论

| 类型 | 组数 | 处置 |
|---|---|---|
| **A. 同物异名（西语/葡语写法）** | 10 | **进 `data/substance_aliases.csv`**（已加 9 组 + 甘露醇拼写 1 组），检索与对照时视为同一成分；**不合并记录** |
| **B. 拼写重复（同一 ATC）** | 1（manitol / mannitol，均 B05BC01） | 可合并为一条（保留中国常用写法 `Mannitol`），需备份 + manifest |
| **C. CJK-only 疑似重复（ATC 不一致）** | 4（炔诺酮、曲安西龙、多黏菌素E甲磺酸钠、地喹氯铵） | **不自动合并**：ATC 码不同，先按 Phase B 规则核对（唯一候选 + ATC 类一致 + 盐型正确），判不了丢弃并计数 |

## 1. A 类：语言写法（已进异名表）

| canonical | 异名 | 依据 |
|---|---|---|
| Bromelain | Bromelaína | 同一中文名「菠萝蛋白酶」 |
| Benzbromarone | Benzbromarona | 「苯溴马隆」 |
| Potassium Iodide | Potasio Ioduro | 「碘化钾」 |
| Mefenamic Acid | Ácido Mefenámico | 「甲芬那酸」 |
| Cyproterone | Ciproterona | 「环丙孕酮」 |
| Clomifene | Clomifeno | 「氯米芬」 |
| Zinc Oxide | Zinc Óxido | 「氧化锌」 |
| Aminosalicylic Acid | Ácido Para Aminosalicílico | 「对氨基水杨酸」 |
| Scopolamine Butylbromide | Butilescopolamina | 「丁溴东莨菪碱」 |
| Water For Injection | Agua Estéril Para Preparaciones Inyectables | 「灭菌注射用水」 |

> 这类不是「重复数据」，是 ES/MX 来源按西语名入库产生的 INN 变体。合并会丢来源；**用异名表连接**即可（task-141）。

## 2. B 类：真重复（可合并）

`manitol`（CN 330 产品，ATC B05BC01）与 `mannitol`（85 产品，同 ATC）——同一 ATC、同一中文名，属拼写差异。
**建议**：Phase B 窗口合并为 `mannitol`（保留中文「甘露醇」），全部产品改挂 `mannitol`；备份 + manifest；合并前后产品数不得变化。

## 3. C 类：CJK-only 疑似重复（4 组，逐个核对）

| CJK 记录 | 疑似对应 INN | ATC 差异 | 判断 |
|---|---|---|---|
| `cn-e7ad153484` 炔诺酮（1 产品） | `noretisterona`（26 产品） | G03AA vs G03DC02 | ATC 属复方码，需看产品成分 |
| `cn-097de24d28` 曲安西龙（1 产品） | `triamcinolone`（342 产品） | A02AC vs H02AB | 曲安西龙=Triamcinolone 中文名，但 ATC 不同（A02AC 为「铝盐类」？）需核对 |
| `cn-259bd4a321` 多黏菌素E甲磺酸钠（1 产品） | `colistimethate`（44 产品） | A07AA vs J01XB01 | 同一成分不同给药部位/ATC，可能应保留两码 |
| `cn-7764ed6be6` 地喹氯铵（22 产品） | `decualinio`（14 产品） | A01AB vs G01AC05 | 同一成分（Dequalinium）不同 ATC，属数据源分类差异 |

**处置**：Phase B 里逐条核对产品成分与 ATC 出处；**能确认同一成分的，用异名表连接（不合并）**；只有 ATC 与中文名都一致才考虑合并。

## 4. 复现 SQL

```sql
-- 15 组同名
SELECT inn_zh, COUNT(*) n FROM substance WHERE inn_zh IS NOT NULL AND inn_zh<>''
GROUP BY 1 HAVING n>1 ORDER BY n DESC;
-- 每组明细（含产品数）
SELECT s.substance_id, s.inn_en, s.atc, s.name_lang,
  (SELECT COUNT(DISTINCT p.product_id) FROM product p
   JOIN product_component pc ON pc.product_id=p.product_id
   JOIN variant v ON v.variant_id=pc.variant_id WHERE v.substance_id=s.substance_id) n
FROM substance s WHERE s.inn_zh=? ORDER BY n DESC;
```

## 5. 边界

- 只读审计；未合并任何记录、未改中文名。
- 合并属数据变更：需备份 + manifest + 合并前后产品/成分计数核对，单独验收。
- 异名表只用于检索/对照，不改变产品身份。
