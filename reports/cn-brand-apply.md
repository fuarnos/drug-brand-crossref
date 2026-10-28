# CN 商品名候选入库准备（task-108）

> 日期：2026-10-29 ｜ 只读真实库 + DB 副本验证 ｜ **未写真实库、未改 build.py、未 git/发布**
> 数据：`data/cn_brand_candidates.csv`（542 行，high 31 / medium 511；NHSA 快照/公示批次 + 江苏/北京/青海/浙江医保局公开查询）
> 产物：`etl/apply_cn_brand_candidates.py`（dry-run/apply/rollback）、本报告、`.tmp/cn-brand-apply/`

---

## 0. 结论

| 项 | 结果 |
|---|---|
| 候选 | 542 行（high **31** / medium **511**）；49 条新品牌行、45 个新名（CSV 标注） |
| 按批文匹配 | `country='CN'` + `approval_id` 精确匹配；**不改产品身份、不合并产品** |
| **实际可挂载**（all） | **232 个产品 / 232 条 product_name(trade)**；84 个候选命中（72 个唯一中文名；12 个新 name_key；13 个新 name_variant；1 个新 source `beijing_ybj`） |
| high 优先 | 50 个产品 / 17 个候选（10 个新 key） |
| 跳过 | **无匹配产品 391**（候选批文不在当前 DB/未来入库）；**无批文号 52**；**已有不同 trade 名 30（conflict，不写）** |
| products/components | **不变**（只加名字链接） |
| 副本验证 | apply high→all：product_name 607,317→607,549（+232）、name_key 168,943→168,955（+12）、name_variant 184,766→184,779（+13）、source 36→37（+1）；quick ok / FK 0；二次 apply 计数不变（幂等）；rollback 后上述计数/hash **与基线完全一致** |
| 窗口 | 已并入 task-133 统一 DB 窗口（CN inn_zh 之后、CN 清洗之前；见 `reports/db-window-20261030.md` §1 步骤 5） |

---

## 1. 规则与数据流

1. **匹配**：`product(country='CN').approval_id == candidate.approval_id`；同一批文多产品时逐产品挂同一品牌名（同品牌多包装），不合并产品。
2. **只补 trade 名**：`product_name(name_type='trade', is_primary=1)`；不改 `substance.inn_en/inn_zh`、不改 product 身份、不删除任何名字。
3. **冲突/重复**：
   - 产品已有同名 trade key → skip(already)；
   - 产品已有**不同** trade 名 → **conflict，不覆盖**（30 例）；
   - 无批文号（52）或无匹配产品（391）→ skip 并存 `.tmp/cn-brand-apply/skipped.csv`。
4. **名称原值**：`brand_name` 原样作为 `name_variant.raw`（不翻译、不改写）；`name_key.key_id = brand_norm`（NFKC/去空格），script 按 CJK 判断 han/latin。
5. **source 归属**：
   - `nhsa_snapshot` / `nhsa_public_batch` → 复用 `nhsa` source；
   - 省级医保局 → 新建 source_id（`beijing_ybj` 实际用到；其余候选未命中产品，暂不建）；source 行含 url/license 说明「政府公开信息；仅事实字段；非商业再发布需署名并可撤下」。
6. **幂等/回滚**：单事务；撤销清单记录新增 product_name/name_key/name_variant/source；`--rollback` 只删「当前仍存在」的链接，已有别人改动则跳过（本次副本验证 0 冲突）。

---

## 2. 统计

### 2.1 CSV 基线

| 项 | 值 |
|---|---:|
| 总行 | 542 |
| confidence high / medium | 31 / 511 |
| 有 db_product_count>0 | 99 行（1 个 43、2 个 25、3+ 个 31） |
| 无批文号 | 52 |
| 按来源 | nhsa_snapshot 465 / jiangsu_ybj 49 / beijing_ybj 19 / nhsa_public_batch 6 / qinghai_ybj 2 / zhejiang_ybj 1 |

### 2.2 可挂载（副本 dry-run）

| 档 | 候选命中 | 挂载产品 | 新 name_key | 跳过：无产品 / 无批文 / conflict |
|---|---:|---:|---:|---|
| high | 17 | **50** | 10 | 12 / 0 / 5 |
| all（high+medium） | 84 | **232** | 12 | 391 / 52 / 30 |

> 391 个「无匹配产品」= 候选批文在当前 DB 中不存在（候选抓取范围大于当前产品集）；建议按季度/下一窗口再核对入库，不影响本窗口。
> 52 个无批文号候选 = 公开页面未带批准文号，无法按批文安全归属，建议补证后再用。

---

## 3. 副本验证

```powershell
$py = '...python.exe'
Copy-Item data\drugs.db .tmp\cn-brand-apply\test.db
& $py etl\apply_cn_brand_candidates.py --dry-run --min-confidence all
& $py etl\apply_cn_brand_candidates.py --db .tmp\cn-brand-apply\test.db --apply --min-confidence high
& $py etl\apply_cn_brand_candidates.py --db .tmp\cn-brand-apply\test.db --apply --min-confidence all
# 幂等：再次 --apply --min-confidence all → product_name/name_key/name_variant 计数不变
& $py etl\apply_cn_brand_candidates.py --db .tmp\cn-brand-apply\test.db --rollback
```

| 检查 | 结果 |
|---|---|
| apply high | +50 product_name / +10 keys / +11 variants |
| apply all（追加 medium） | 累计 +232 product_name / +12 keys / +13 variants / +1 source |
| 二次 apply all（幂等） | 计数不变（607,549 / 168,955 / 184,779） |
| quick / FK | ok / 0 |
| rollback | product_name 607,549→**607,317**、name_key→**168,943**、name_variant→**184,766**、source→36；product_name 内容 hash 与基线一致；quick/FK ok |
| products/components | 全程不变（431,555 / 534,246） |

---

## 4. 真实窗口步骤（并入 task-133）

1. 前置：task-133 备份 + 前序步骤（HK/EMA/CN inn_zh）完成。
2. 命令（推荐 high 先跑，确认后再 all）：
   ```powershell
   & $py etl\apply_cn_brand_candidates.py --apply --allow-real --min-confidence high --manifest .tmp\cn-brand-apply\manifest.json
   & $py etl\apply_cn_brand_candidates.py --apply --allow-real --min-confidence all  --manifest .tmp\cn-brand-apply\manifest.json
   ```
3. 期望：+232 product_name（上限；若后续 CN 清洗删除重复产品，部分名字会 cascade 减少，以实际为准）；products 不变；quick/FK ok。
4. 回滚：`& $py etl\apply_cn_brand_candidates.py --rollback --allow-real --manifest .tmp\cn-brand-apply\manifest.json`；整库回退用 task-133 备份。
5. 顺序建议：按 Lead task-133 顺序放在 **CN inn_zh 之后、CN 清洗之前**；若希望新名覆盖更多产品，也可在 CN 清洗后执行（需 Lead 决定，两种都安全；本报告按 Lead 顺序）。

---

## 5. 风险 / 注意

| # | 风险 | 说明 |
|---|---|---|
| 1 | 511 个 medium 候选 | 来源为公示批次/省级挂网，可能滞后或含包装差异；建议 high 先上线，medium 抽检品牌/批文一致后 all；窗口记录 both 计数 |
| 2 | 391 个候选无匹配产品 | 不写入；未来产品入库后重跑 dry-run 可挂 |
| 3 | 52 个无批文号 | 不写入；补证（批文/说明书）后再用 |
| 4 | 30 个 conflict（已有不同 trade） | 不覆盖；人工核对哪个是注册商品名（可能现有名是通用名/旧名） |
| 5 | 省级 source 许可 | 仅事实字段，页面/About 署名与可撤下说明；`beijing_ybj` 本次唯一新增 source |
| 6 | 与 CN 清洗顺序 | 若先挂名、后清洗删重复产品，部分新名 cascade 消失；记录净增，必要时清洗后重跑 apply（幂等） |
| 7 | 同名不同批文 | 按批文分别挂，不合并产品；与 collision 规则一致 |

---

## 6. 证据

| 文件 | 内容 |
|---|---|
| `.tmp/cn-brand-apply/dryrun_all2.out.txt` / `dryrun_high.out.txt` | dry-run 统计（all/high） |
| `.tmp/cn-brand-apply/dryrun.json` / `dryrun_high.json` | 计划明细 |
| `.tmp/cn-brand-apply/skipped.csv` | 跳过明细（no_product/no_approval/conflict） |
| `.tmp/cn-brand-apply/apply_high.out.txt` / `apply_all.out.txt` / `apply_all2.out.txt` | apply 日志 |
| `.tmp/cn-brand-apply/manifest.json` | 撤销清单（232 条链接 + 12 keys + 13 variants + source） |
| `.tmp/cn-brand-apply/verify.py` / `pristine.db` / `test.db` | 计数/hash/quick/FK 前后对比 |

_本报告由并行子智能体 data-depth 生成；未写真实库、未改 build.py、未 git/发布。_
