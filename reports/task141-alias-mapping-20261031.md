# task-141 同物异名映射（数据层 + 加载器 + 测试）

> 执行：2026-10-31 谷段（00:35 起，自治运营）。只读开库、**未改 `data/drugs.db`**、未建站、未发版。
> 前置：`reports/task140-crossref-audit-20261030.md`（双向对照审计，2026-10-30）。

## 0. 结论

- 已建**同物异名对照表** `data/substance_aliases.csv`：**14 行 / 8 组**，覆盖 task-140 里 CN→US 的 6 条、US→CN 的 2 条命名缺口（葡萄糖↔Dextrose、扑尔敏、头孢氨苄、甘油、甘露醇拼写、格列本脲、沙丁胺醇、环孢素、东莨菪碱、异丙肾上腺素、呋塞米、肾上腺素）。
- 已建加载器 `lib/aliases.py`（并查集，纯文件、不碰库）+ 单元测试 `lib/test_aliases.py`：**12 项全 OK**（含「表里 id 必须真实存在于库」的只读校验）。
- `db/crossref_audit.py` 已改为读这张表（硬编码的 12 组已删除），审计结果与 2026-10-30 一致、但以后加词只改 CSV 一行。
- **站点侧尚未接入**（`site/build.py` / `assets/app.js` / `lib/search.py`），原因见 §3：需要一次构建串进 v0.9.6 批次，避免为一张小表单独构建 20 分钟。

## 1. 表内容（`data/substance_aliases.csv`）

| canonical | alias | relation | 依据（source） |
|---|---|---|---|
| Glucose | Dextrose | synonym | INN vs USAN（美国标签用 Dextrose） |
| Glucose | Anhydrous Dextrose | hydrate_variant | 美国标签写法 |
| Chlorphenamine | Chlorpheniramine | synonym | INN vs USAN |
| Glycerol | Glycerin / Glycerine | synonym / spelling | INN vs USAN + 拼写 |
| Manitol | Mannitol | spelling | 库内拼写不一致 |
| Glibenclamide | Glyburide | synonym | INN vs USAN |
| Salbutamol | Albuterol | synonym | INN vs USAN |
| Cefalexin | Cephalexin | synonym | INN vs USAN |
| Hyoscine | Scopolamine | synonym | 英国/澳洲用 Hyoscine |
| Isoprenaline | Isoproterenol | synonym | INN vs USAN |
| Ciclosporin | Cyclosporine | synonym | INN vs USAN |
| Furosemide | Frusemide Sodium | synonym_salt | INN vs USAN + 钠盐写法 |
| Epinephrine | Adrenaline Acid Tartrate | synonym_salt | INN vs USAN + 盐型写法 |

字段：`canonical_inn, canonical_id, alias_inn, alias_id, relation, source, note`。**source 必填**（测试会拦），判不了的写法不进表。

## 2. 代码

- `lib/aliases.py`：`load()` → `AliasMap`；API `canonical(id)` / `group(id)` / `aliases(id)` / `lookup_name("Dextrose")` / `same(a,b)`；名称归一忽略大小写与标点。
- `lib/test_aliases.py`：文件存在、行数、relation 合法、无自指/重复、每条有 source、对称性、名称查询、未知返回空、**id 在库校验**（`mode=ro`）。
- `db/crossref_audit.py`：`synonym` 判定改为 `am.aliases(sid)`，删掉内置 12 组硬编码；重跑结果不变（CN 6 条同物异名 / US 2 条）。

## 3. 为什么还没上站点

站点检索吃的是 `site/build.py` 生成的 `data/idx/core.json` + 客户端 `app.js`，不是 `lib/search.py`。要真正「搜 Dextrose 出葡萄糖」，需要同时改：

1. `site/build.py`：把异名写进对应条目的可检索名集合（或生成 `data/idx/aliases.json`）；
2. `assets/app.js`：查询命中异名时把同组条目一并返回，并标 `match_source=inn_alias`（与俗称 `nickname` 区分）；
3. `lib/search.py`：CLI / 三语测试同口径（否则站点与 CLI 行为不一致）。

三处一起改 + 全量构建（~20 分钟）+ 三语回归（~10 分钟）+ 发布（~20 分钟）。按「一次构建串多个任务」的约定，**并入 v0.9.6**（与 task-142 导航 / task-145 ATC4 同一批），不单独为此发版。

## 4. 顺带发现的数据质量问题（写进 task-5 Phase B 输入）

1. **`Glycerol` 的 `inn_zh` 是「开塞露」**——这是剂型/商品型名，不是成分名，应改为「甘油」。
2. **`Manitol` 与 `Mannitol` 两条**的 `inn_zh` 都是「甘露醇」——同一中文名指向两个 substance，检索会歧义；确认后应保留一条。
3. **`Chlorphenamine` 的 `inn_zh` 是「马来酸氯苯那敏」**——中文名里带盐，与 base 名不一致；同类还有若干（盐在中文名内）。
4. 以上都属「名称清洗」，不涉及身份合并；改动需走 DB 窗口（备份 + manifest），已列入 v0.9.5 Phase B 同窗口。

## 5. 验证

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py -m unittest lib.test_aliases -v          # 12 OK
& $py db/crossref_audit.py --top 100           # 与 10-30 结果一致，改由 CSV 驱动
& $py deploy/ci_checks.py --fast               # py_compile 142 文件 / etl 25 / lib 41 / mobile 29 / dist 完整性 121,290 · sitemap 63,363
```

## 6. 边界

- **不做身份合并**：`drugs.db` 未改，`substance` 主键未动，产品归属不变；表只用于「检索与对照」。
- 不判断可替代：异名只说明「是同一成分的不同写法」，不说疗效等价。
- 表是人工小表：新增必须有来源（说明书 / 药典 / 官方标签），宁缺勿滥。
