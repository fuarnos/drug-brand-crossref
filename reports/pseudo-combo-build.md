# 伪复方 build 层 base 归并报告（v0.8.3）

> 依据 `reports/pseudo-combo-audit.md`（545 假 combo key / 8,798 产品 / severe 477+info 67）。
> 任务：v0.8.3 批次（task-119 之后）build 层归并；**未写 DB**、未改 data/markets/languages/tests/site/dist。
> 构建：`SITE_OUT=.tmp/dist-pseudo`；对照基线 `.tmp/dist-filter`（build 层归并前）。

## 0. 结果

| 项 | 结果 |
|---|---|
| 归并规则 | 严格 base+salt：末尾 salt/hydrate/ester 词表逐个剥离，找到**存在的 base substance**即映射；元素基（sodium/calcium 等）不并；同名重复 substance（如 `povidone-iodine` / `povidone-iodine-<hash>`）canonical 归一；**递归到不动点**（如 Alendronate Sodium Trihydrate → Alendronate Sodium → Alendronate） |
| 展示 | 索引 `x` 只显示 base 名（不再 `Ferrous + Ferrous Gluconate`）、`vs` 为空、`cu` 为空；结果成分列回退 drug 页（既有规则） |
| 假 combo 页 | **10,942 → 10,284（-658）**（目标 545 假 combo；另含同名重复 substance 合并等 113 页） |
| collision | 伪复方 key 归并为单 base 后 entry level 覆盖为 `info`：severe 条目 **19,381 → 18,862（-519）** |
| 真实复方 | combo 页仍 **>10,000**；`amoxicillin clavulanate` 等仍显示 combo 链接（headless 验证） |
| 构建 | exit 0；**62,217 文件 / 468.4 MB**；sitemap **62,057**（-534）；name 31,134；core 32.5 MB |
| 验证 | 静态 **7/7**、headless 全通过（`aadfer` 不再 Ferrous+Ferrous、无假 combo、无 severe；真实复方保留）；CSV 抽样 120 个伪复方 key 全部无 `vs/cu/severe` |

## 1. 改动清单（`site/build.py`）

| 内容 | 位置 |
|---|---|
| `SALT_WORDS` / `_SALT_ELEMENTS` / `_salt_base_of` | load_index 前 |
| `sub_names/by_norm/canon/salt_to_base` 映射 + 递归 resolve（base 归并、同名 canonical） | `load_index()` 开头/行循环 |
| 归并后 `sids` 去重 → `vs/cu` 为空；`merged_keys` 的 entry `l="info"` | `load_index()` entry 构造 |
| combo 页自然减少（`build_combo_pages` 只处理 `vs`） | 无需改算法 |

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-pseudo'; & $py -X utf8 site/build.py   # exit 0, 468.4 MB
& $node --check .tmp\dist-pseudo\assets\app.js                     # 0
& $py -X utf8 <verify>/static_check.py '<repo>\.tmp\dist-pseudo' '<repo>' '<repo>\.tmp\dist-filter'  # 7/7
# 临时 http.server 8819 + headless.mjs → ALL CHECKS PASSED
```

- **静态 7/7**：shard 条目可读；severe 19,381→18,862；combo 10,942→10,284（-658，≥400）；真实 combo >10,000；CSV 抽样 120 个伪复方 key 无重复 base/无 vs/无 cu/非 severe；伪复方 key 不再生成 combo 页；无 0 字节。
- **Headless**：搜索 `aadfer` → 成分只显示 `Ferrous`（不再 `Ferrous + Ferrous`）、无 combo 链接、无 severe/同名不同药；搜索 `amoxicillin clavulanate` → 真实复方仍显示 combo 链接。
- 典型样例：`5% glucose`、`calcium chloride`、`donepezil`、`povidone-iodine`、`alendronate wgr` 等已归并。

## 3. 风险 / 已知事项

1. **盐词表覆盖**：只处理标准 salt/hydrate/ester 词；非常见盐名/首词相同但非盐（胰岛素、无机盐等）不并（按审计建议人工核对），残留的假 combo 归入后续 task-131/138 数据核对。
2. **同名重复 substance**：`povidone-iodine` 等带 hash 后缀的重复项被 canonical 合并（属于展示层归并，DB 仍两份）。
3. **数据层 214 产品重复成分**（base+salt 同产品两行）未在 build 修复；数据任务 `etl/fix_pseudo_combos.py` 另行处理（副本已验证）。
4. **collision 页面/计数**：DB `collision` 视图仍按原始 substance 计；页面 entry 级别已覆盖为 info，About 数字口径暂不变（后续数据归并后可统一）。
5. **combo 页减少 658**（比审计 545 多 113）：含同名 canonical 合并与多层 hydrate 归并，均属 base+salt 展示去重；sitemap 同步减少。

## 4. 回滚

`git checkout -- site/build.py` 后重建；或仅回退 SALT/canon/递归 resolve 映射与 entry level 覆盖（combo 页/索引恢复原状）。

## 5. 产物

- `.tmp/dist-pseudo/`（62,217 文件 / 468.4 MB）。
- 验收脚本：`static_check.py`、`headless.mjs`（TEMP `pseudo-verify-20261028/`）。
- `reports/pseudo-combo-build.md`：本报告（在 `pseudo-combo-audit.md` 基础上补 build 层结果）。
