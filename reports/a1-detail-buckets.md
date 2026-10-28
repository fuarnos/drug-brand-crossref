# A1 产品详情数据桶（detail-*.json）— task-58

> 日期：2026-10-28 · 任务：task-58 · 状态：**桶生成 + 体积/覆盖校验完成**（未写 DB、未改 `site/build.py`、未发布）
> 脚本：[`etl/build_detail_buckets.py`](etl/build_detail_buckets.py)（~470 行，只读 DB；`--stats-only` 先估再写）
> 产物：[`data/idx/detail-*.json`](data/idx)（51 个桶，生成物）；证据：`.tmp/a1-detail/{stats.json,sample_check.json,verify.json,probe.json}`
> 依据：`reports/ui-a1-b6-plan.md` §2 A1（懒加载明细桶，不新增 40 万页、不塞主索引）

---

## 1. 结论摘要

| 指标 | 结果 | 预算 | 结论 |
|---|---:|---:|---|
| 桶数 | **51**（拉丁 26 + 数字 1 + CJK 23 + other 1） | 40–55 | ✅ |
| key 数 | **127,085**（= 索引全部 `k`，0 缺失/0 多余/0 重复） | — | ✅ |
| 明细行数 | **294,895**（平均 2.32 行/key；每 key ≤12） | — | ✅ |
| **raw 体积** | **46.93 MB**（46,932,192 B） | ≤55 MB | ✅（余量 14.7%） |
| **gzip 体积** | **9.31 MB**（9,307,836 B，逐桶 gzip -9 求和） | ≤10 MB | ✅（余量 6.9%，偏紧） |
| 每 key 行数上限 | **12（未降级）** | 12 起可降 8 | ✅ 无需降级 |
| 最大单桶 | `detail-a.json` 4.16 MB raw / 0.86 MB gz（26,623 行） | — | ⚠️ 见 §6 |
| 最小单桶 | `detail-other.json` 7.8 KB raw / 1.7 KB gz（7 key） | — | — |
| 字段/解码校验 | 3 桶抽样 9 条产品与 DB 逐字段一致（`sample_check.all_ok=true`） | — | ✅ |

**做法**：直接从只读 `data/drugs.db` 生成「key → 最多 12 条产品明细」桶；用 build.py 同款 `_shard_bucket(k)` 分桶；桶内做**枚举字典 + URL 前缀压缩**，把平铺估算的 71.7 MB raw 压到 46.9 MB，同时保留任务要求的全部 11 个字段（外加 `source_id` 索引）。**首屏不加载任何 detail 文件**；点「详情」时按索引条目 `db` 字段拉单桶（平均 gz ≈183 KB，最大 860 KB）并缓存。

---

## 2. 体积评估与降级记录

平铺原文字段（11 字段 + product_id）估算 **243.5 B/行**：cap12 = 294,342 行 ≈ **71.7 MB raw**（超 55 MB）；cap8 ≈64.7 MB 仍超。压缩方案：

| 优化 | 效果 |
|---|---|
| status / release / source_id 改桶级枚举下标 | 每行省 ~25 B |
| URL 前缀压缩（同桶同 source 取公共前缀，行内存后缀） | URL 字符串 18.23 MB → 省 **16.67 MB（91.4%）** |
| 紧凑数组 + `separators=(",",":")` | 每行 ≈159.1 B |

三种 cap 实测（`--stats-only`，本机同库同索引）：

| max_rows/key | 行数 | raw | gzip | 是否满足预算 |
|---:|---:|---:|---:|---|
| **12（采用）** | **294,895** | **46.93 MB** | **9.31 MB** | ✅ |
| 10（降级备选） | 281,895 | 45.03 MB | 9.05 MB | ✅ |
| 8（降级备选） | 266,173 | 42.75 MB | 8.72 MB | ✅ |

> gzip 余量只有 ~6.9%：数据量再涨约 5–7% 会破 10 MB；脚本默认按 12→10→8 自动降级并在 `stats.json` 记录 `degraded`。若后续采用该产物，建议 CI/发布前跑一次 `--stats-only` 检查预算。

---

## 3. 桶文件格式（v1，接入契约）

```jsonc
{
  "v": 1,
  "t": ["active","discontinued","withdrawn","unknown"],     // status 枚举
  "r": ["none","IR","ER","SR","DR","MR","GITS"],           // release 枚举
  "s": ["openfda_ndc", "..."],                             // source_id 表（全局一致，约 27 项）
  "p": ["https://…", "…"],                                 // 每个 source 在本桶的 URL 公共前缀
  "k": {
    "<key_id>": [
      [product_id, country, brand, pack, approval_id, status_idx,
       status_date, release_idx, strength, mah, source_url_suffix, source_idx],
      ...
    ]
  }
}
```

- 字段顺序常量：`etl/build_detail_buckets.py` 的 `ROW_FIELDS`（12 项），与任务字段对照：
  `product_id` ✅ / `country` ✅ / `brand` ✅ / `pack` ✅ / `approval_id` ✅ / `status` ✅ / `status_date` ✅ /
  `release` ✅ / `strength` ✅ / `MAH` ✅ / `source_url` ✅（存后缀）+ `source_id`（额外，索引）。
- 客户端重建（必须）：
  `url = p[row[11]] + row[10]`；`status = t[row[5]]`；`release = r[row[7]]`；`source_id = s[row[11]]`；
  `brand / pack / mah / strength` 为原串，空串 → 显示 `—`。
- 选取规则：`product_name(name_type IN ('trade','inn')) ⋈ product`；按 `status=active 优先 → country → product_id` 排序；同 key 内按 product_id 去重；每 key 取前 ≤`max_rows` 条。
- `brand` = 该产品第一个 `trade` 名（`name_variant.raw`）；`strength` = 成分强度串（多成分 `500 mg + 125 mg`，含 per-volume 时追加 `5 ml`）。
- 与 `reports/ui-a1-b6-plan.md` §2.3 草案的差异：计划是 9 字段平铺；本产物按 task-58 字段要求扩到 11+1 字段，并用枚举/URL 后缀压到预算内 → **前端 `detPanelHTML` 的列索引要按上表改**（B6/A1 接入任务注意）。

---

## 4. 桶分布（51 桶）

| 类型 | 桶数 | 说明 |
|---|---:|---|
| 拉丁字母 | 26 | a–z，按 key 首字符 |
| 数字 | 1 | `digit` |
| CJK | 23 | `cjk-<拼音首字母>`（build.py `_shard_bucket` + `_pinyin_dict`，全部与索引桶函数一致） |
| 其他 | 1 | 7 个 key / 37 行 |

Top 8（raw / gzip / 行数）：

| 桶 | keys | rows | raw | gzip |
|---|---:|---:|---:|---:|
| a | 12,461 | 26,623 | 4.16 MB | 0.86 MB |
| c | 10,505 | 21,462 | 3.39 MB | 0.70 MB |
| s | 9,952 | 18,164 | 3.02 MB | 0.63 MB |
| p | 8,007 | 17,013 | 2.54 MB | 0.54 MB |
| m | 6,748 | 14,529 | 2.23 MB | 0.47 MB |
| b | 7,241 | 13,332 | 2.19 MB | 0.47 MB |
| i | ~5.3k | ~11k | ~1.9 MB | ~0.41 MB |
| t | ~5.7k | ~12k | ~2.0 MB | ~0.43 MB |

CJK 桶都很小（最大 cjk-l ≈1.7k key / ~0.3 MB raw）；`detail-other` 最小。完整 51 桶清单见 `.tmp/a1-detail/stats.json → bucket_sizes`。

---

## 5. 校验（`.tmp/a1-detail/verify.json`）

- 文件数 51；`Σ raw=46,932,192 B`；`Σ gzip -9=9,307,836 B`；行 294,895；key 127,085；
- **覆盖**：`missing_keys=0`、`extra_keys=0`、`duplicate_keys=0`（索引每个 `k` 恰好落在一个桶）；
- 桶函数：直接 import `site/build.py:_shard_bucket`（抽查 `lipitor→l`、`葡萄糖注射液→cjk-p`），与后续索引 `db` 字段天然一致；
- **抽样解码**：`detail-l / detail-a / detail-cjk-l` 各取首行，`product_id/country/status/release/source_id/source_url` 与 DB 查询逐字段一致（`sample_check.all_ok=true`；URL 重建后均 `http(s)://` 开头）；
- JSON 全部 `json.loads` 通过；最大行数组序列化 ~350 B（含长 pack/url）。

---

## 6. 加载策略（给前端/接入任务）

1. 索引条目新增 1 个短字段：`entry["db"] = _shard_bucket(key_id)`（`site/build.py` `load_index()` 的 entry dict，当前在 `build.py:3254` 附近，`"k": key_id` 同处；`encode_core` 建议把它放 `CORE_DICT_COLS`，体积几乎不增）。
2. 结果行「详情」按钮点击 → `fetch(BASE + 'data/idx/detail-' + e.db + '.json?v=' + MANIFEST.v)`；`Map` 按桶缓存（同一字母桶一次）；`aria-expanded` 折叠/展开；加载中 skeleton，失败/404 → 降级链到成分页 `drug/<v>.html`。
3. **首屏零成本**：detail 文件不参与 manifest/core/分片，也不进 service-worker 预缓存；只有点击才请求。单桶平均 raw 0.92 MB / gz ≈183 KB；最大 a 桶 0.86 MB gz（弱网首展开 ~1–3 s，需 loading 态）。
4. 每个 key 只展示 ≤12 行；超过时显示「共 N 条，全部见成分页」（N 用索引 `e.n`）。
5. `?legacy=1` 路径不受影响（`index.json` 也带 `db` 字段；detail 文件 404 时按钮降级）。
6. 发布：`site/build.py` 构建时需要把 `data/idx/detail-*.json` 复制进 `OUT/data/idx/`（约 +51 文件 / +46.9 MB raw 到 dist；`publish.ps1` 文件数门槛 24,000 仍满足）。`data/idx/` 是生成物，建议在发布/构建流水线中由本脚本重新生成，避免与 DB/索引不同步。
7. 文案/i18n：`a1.expand/loading/none/goto/pack/approval/status/source/raw/more`（三语，见计划 §2.5）。

---

## 7. 接入步骤（给能改 build.py 的任务；锚点按当前 4,607 行快照）

| 步骤 | 位置 |
|---|---|
| ① entry 加 `db` | `def load_index`（`build.py:3151`）的 entry dict（`"k": key_id` 在 `3254`）→ 追加 `"db": _shard_bucket(key_id)` |
| ② core 字典列 | `encode_core` 的 `CORE_DICT_COLS` 加 `"db"`（`decodeCore` 通用解码，不用改 JS） |
| ③ 复制桶文件 | `main()` 里 `shards = encode_shards(entries)`（`build.py:4528`）之后：`shutil.copytree(ROOT/'data'/'idx', OUT/'data'/'idx', dirs_exist_ok=True, ignore=…)` 仅复制 `detail-*.json`；build.py 已 `import shutil`（L29） |
| ④ 客户端 | `loadDetailBucket()` + 面板渲染（计划 §2.4 草案，按 §3 重建字段）；事件委托加 `[data-det]`；CSS `.detrow/.det/.detcell`；i18n |
| ⑤ 验收 | 抽 US/GB/CN/CA 各 1 行展开/折叠；断网/404 降级；移动端不溢出；`index.json` 增幅 <1 MB；页面数 +51；`?legacy=1` 正常 |
| ⑥ 构建期防漂移 | 桶的 `k` 列表来自生成时的 `index.json`；若 build.py 重建索引后 key 变化但未重跑本脚本 → 缺 key（前端表现为「无数据」）。建议 build 时检查 `data/idx/detail-*` 的 `stats.json.generated_at` vs `index.json` mtime，不一致则 `SystemExit` 提示重跑；或在 build.py 内直接调用本脚本（届时可去掉文件复制） |

---

## 8. 风险 / 余量

| 风险 | 说明 | 缓解 |
|---|---|---|
| gzip 预算偏紧 | 9.31/10 MB（余量 6.9%）；DB 继续增长会破线 | 自动降级 cap10（9.05 MB）/cap8（8.72 MB）；发布前跑 `--stats-only` |
| 最大单桶 a 0.86 MB gz | 弱网首次展开慢于计划（计划 200–350 KB/桶）；平均桶 183 KB | 先 loading；后续可把 a/c/s/p/m 细分（`db` 值改 `a-1/a-2`，需与 `_shard_bucket` 同步改） |
| 与计划字段不一致 | 计划 §2.4 草案用 9 字段平铺；本产物 12 字段紧凑编码 | 前端按 §3 重建（url/status/release/source）；报告已标明 |
| 数据漂移 | DB 被并行入库任务改动时，桶内容旧 | 只读快照 + `stats.json.generated_at`；接入时做 mtime/大小校验 |
| repo 体积 | `data/idx` 新增 46.9 MB raw（git 内部压缩约 9.3 MB） | 若不想进仓库可改 `.gitignore` + 构建期生成；但任务要求生成物落 `data/idx`，当前保留 |
| 行排序/截断 | 每 key 只显示前 12 条，`active` 优先；其余需求「全部见成分页」 | 前端用 `e.n` 提示总数；不伪造数据 |
| 合规 | 详情只含事实字段（产品号/包装/状态/厂家/来源链接），无说明书正文 | 沿用源许可（详见 `reports/tw-tfda-audit.md` 等）；source_url 保留出处 |

---

## 9. 复现 / 证据

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py etl\build_detail_buckets.py --stats-only   # 只估体积（cap 12/10/8 对比）
& $py etl\build_detail_buckets.py                # 写 data/idx/detail-*.json（自动预算降级）
& $py .tmp\a1-detail\verify.py                   # 覆盖/体积/解码校验 → verify.json
```

- 脚本：`etl/build_detail_buckets.py`（`py_compile` 通过；只读 DB `mode=ro`，前后 `data/drugs.db` 未变）。
- 产物：`data/idx/detail-<bucket>.json` × 51（`detail-a.json` … `detail-other.json`）。
- 统计：`.tmp/a1-detail/stats.json`（体积/桶分布/URL 编码收益/降级记录）、`sample_check.json`、`verify.json`、`probe.json`（尺寸估算）。
- 生成时点：`site/dist/data/index.json` 127,085 条（2026-10-28 10:25 构建快照）；DB 只读快照 409,587 products / 568,907 product_name。

**一句话**：51 桶、294,895 行、46.93 MB raw / 9.31 MB gzip，全部预算内且 0 key 缺口；按 `db=_shard_bucket(k)` 懒加载单桶即可，接入只改 `load_index` 加 1 个字段 + 复制文件 + 前端面板（后续任务）。
