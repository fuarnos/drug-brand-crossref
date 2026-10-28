# 索引 P2 分片接入（task-36）

> 日期：2026-10-27 · 任务：task-36 · 状态：**已接入 `site/build.py`**（独占文件；搜索 v2 / UI P0 / i18n 均保留）
> 构建验证：`SITE_OUT=.tmp/dist-p2/dist`（`== done ==`，30,327 files / 197.4 MB）
> 未改 `site/dist`、`data/drugs.db`；未跑 git / 发布。
> 接入前快照：`.tmp/dist-p2/build_before.py`（回滚用）。`site/build.py` 3704→3870 行（+185 / −19），sha256 `516e2e3e…`。

---

## 0. 结论（指标）

| 指标 | 接前（P1 core 全量） | 接后（P2 分片首搜） | 变化 |
|---|---:|---:|---:|
| **首搜 gzip 字节**（manifest+分片+aliases+confused） | **3.78 MB**（core 3.68 + aliases 0.091 + confused 0.001） | **254 KB p50 / 270 KB p90**（= manifest 6.3 KB + 1 片 ~155 KB + aliases 91 KB） | **≈14.9× 更小** |
| 首搜失败/不可路由回退 | — | 2/384 条查询回退 core（3.67 MB，等同现状） | — |
| 匹配延迟（Node 桌面，内存扫描，不含网络） | P50 92.2 ms / P90 148.1 ms | **P50 2.68 ms / P90 5.51 ms**（分片池线性扫描；分片 JSON.parse 另计 P50 2.5 ms） | P50 ≈34× |
| 354 三语 Top-1 / Top-5（**core 到位后的最终态**） | 96.89% / 97.18% | **96.89% / 97.18%** | 持平（未回归） |
| 首帧（core 前）分片池 Top-1 / Top-5（353 条可路由） | — | 92.63% / 92.63%（exact/前缀完整；contains/别名/模糊/国家视图等 core 后补全） | 渐进增强窗口 |
| `?legacy=1` | index.json 6.06 MB | 6.06 MB（不变，DOM 已验证） | — |
| DOM 行为测试（jsdom） | — | **15/15 断言通过**（含「分片先于 core」、拼音/国家视图/legacy、最终态与 legacy 逐字一致） | — |
| 发布影响 | 30,258 files / 160.5 MB | 30,327 files / **197.4 MB**（+69 文件 ≈ +37 MB raw：68 分片 + manifest） | 见 §7 |

**一句话**：首搜从「3.78 MB 全量 core」变成「**254 KB（manifest + 1 个分片）**，core 在后台补全」；最终检索结果与接入前逐字一致，`?legacy=1` 与全部失败路径均可回退。

---

## 1. 实现设计

### 1.1 构建期（`site/build.py`，main() 内新增，见 file:line）

- 从 `entries`（126,915 条）派生 **51 个桶**：
  - 拉丁首字母 `a`–`z`（26 桶）；数字 `digit` 桶；符号 `other` 桶；
  - CJK 按**首字拼音首字母**分桶（`cjk-a` … `cjk-x`，24 桶）——复用 task-28 内嵌的 1,582 字拼音表；
  - 954 个「CJK 首字 → 桶」映射写入 manifest，供客户端**不加载拼音表**即可按首字路由。
- 每桶内按 `k` 排序，按原始字节 ~1.1 MB 切成 1..n 个分片 → 共 **68 个分片**（`data/idx/shard-<bucket>-<i>.json`，条目结构与 `index.json` 相同，客户端直接渲染）。
- manifest（`data/idx/manifest.json`，22,115 B raw / **6,285 B gzip**）：
  `{v:<build ts>, n, buckets:{bucket:[{f,first,last,n,bytes}...]}, cjkInitials:{首字:桶}, core:{f,bytes}, shardCount:68, shardBytes:34.8MB}`。
- 保留 `data/idx/core.json`（3.68 MB gz）作为完整回退；`index.json`（6.06 MB gz）供 `?legacy=1`；拼音表 `pinyin.json` 仍独立懒加载。

### 1.2 客户端流程（`APP_JS`）

```
首次输入 / ?q= 深链
  └─ fetch manifest(6KB) + aliases/confused(91KB)
       ├─ 路由：首字符 → 桶；取与该前缀相交的 1–3 个分片（CJK 桶通常 1 片）
       ├─ fetch 分片（~30–175KB）→ IDX=分片池 → render()（partial：exact/prefix/同字母桶模糊可用；
       │    国家视图 / 同成分 / 家族 / contains 跨桶 / 别名 / ARTG 延后，meta 提示「部分结果 —— 正在加载完整索引…」）
       └─ 后台 setTimeout loadIndex(true)：拉 core.json(3.68MB) → 解码 → 建搜索派生层 → 重渲当前查询（完整语义）
后续输入：若新查询需要未加载的桶 → 追加拉 1–3 片（POOL_FILES 去重）；core 已到则直接全量路径
失败：manifest/分片 404 或异常 → loadIndex() 拉 core；core 失败 → 保留分片视图并 console.warn
?legacy=1：页面加载即拉 index.json，走旧逻辑，不碰 manifest/core
```

### 1.3 关键实现点（本轮修掉的坑）

- **core/shard 竞态**：分片请求慢于后台 core 时，`loadShards` 若仍用分片池覆盖 `IDX` 会导致索引错位（`reading 'k'` 崩溃）→ 加 `if(IDX_READY) 丢弃分片追加` 保护。
- **自动完成抢跑 core**：`input` 事件里 `acUpdate()` 原先在无索引时直接 `loadIndex()`，把首搜从分片拉回全量 core → 改为「分片加载中（`SHARD_P`）不抢跑」。
- **拼音兜底**：冷启动时模糊结果（如 `tainuo`→Wainua）会阻止拼音表懒加载 → 触发条件放宽为「零命中或**只有 fuzzy 命中**」；DOM 验证 `tainuo` 出秦诺/泰诺（`Matchpinyin`）。
- **ARTG 兜底**：partial 阶段不触发 4.9 MB `artg.json`，core 到位后恢复。
- **焦点预取**：从「预取 3.8 MB core」改为「预取 manifest + aliases/confused」。

---

## 2. 改动清单（file:line）

| 位置 | 改动 |
|---|---|
| L125 / L255 / L383 | I18N 新增 `res.partial`（en/es/zh：部分结果——正在加载完整索引…） |
| L1418 | 全局：`MANIFEST / MANIFEST_P / SHARD_CACHE / POOL_READY / POOL_FILES / SUPPORT_P / SHARD_P` |
| L1690 | `acUpdate()`：分片加载中不抢跑 core（`if(!SHARD_P) loadIndex()`） |
| **L2292–L2355** | 新增分片函数块：`fetchManifest / loadSupport / shardKeyOf / shardsForQuery / loadShards / loadShardedIndex / ensureCoreInBackground` |
| L2356–L2388 | `loadIndex(quiet)`：支持后台静默加载（不显示 loading hint；成功且静默时重渲；失败保留分片视图）；复用 `loadSupport()`；保留 P1 派生层构建 |
| **L2390–L2408** | `startSearch()` 重写：分片优先 → partial render → 后台 core；已加载桶复用；失败回退 core；`LEGACY` 走旧路 |
| L2011 | `render()`：`partial` 标记；国家视图/同成分/家族/ARTG 在 partial 阶段降级 |
| L2015–L2018 | 拼音懒加载触发条件放宽（零命中或只有 fuzzy） |
| L2071 | partial 时 meta 追加 `res.partial` |
| L2493 | 焦点预取改为 manifest + support |
| L3593–L3606 | Python：`_shard_bucket()`（首字母/数字/CJK 拼音首字母/other） |
| **L3608–L3657** | Python：`encode_shards(entries)`：分桶、切片、写 68 个分片 + 生成 manifest（含 cjkInitials/core 信息） |
| L3738 | app.js 版本替换链新增 `data/idx/manifest.json?v=<ts>` |
| L3797–L3802 | `main()`：core 写出后生成 manifest + 分片并打印体积 |

---

## 3. 构建产物与体积

| 文件 | raw | gzip9 | 说明 |
|---|---:|---:|---|
| `data/idx/manifest.json` | 22,115 B | **6,285 B** | 桶/分片边界 + 954 个 CJK 首字映射 |
| `data/idx/shard-*.json`（68 个） | 34,791,340 B | **5.48 MB**（p50 44 KB/片，最大 175 KB） | 按桶切分，36/68 片 <60 KB |
| `data/idx/core.json`（保留） | 15.26 MB | 3.68 MB | 完整回退 |
| `data/index.json`（`?legacy=1`） | 34.79 MB | 5.82 MB（线上 6.06 MB） | 不变 |
| `data/aliases.json` | 869 KB | 91 KB | 首搜随 manifest 一起拉（昵称语义需要） |
| `assets/app.js` | 52,195 B | 17,926 B | +4.3 KB（分片逻辑） |
| `site/dist` 合计 | — | — | 30,327 files / 197.4 MB（+69 files / +37 MB raw） |

桶大小极值（整桶 gzip 合计）：`a` 4 片/533 KB、`c` 3 片/442 KB、`b` 2 片/322 KB、`l` 2 片/~190 KB；CJK 桶均 1 片（2–39 KB，如 `cjk-f` 37 KB、`cjk-l` 39 KB、`cjk-d` 24 KB）。单次查询按前缀只取 1 片（跨边界 ≤2；CJK 1 片）。

---

## 4. 首搜体积与延迟（`bench_p2.mjs`，直接 eval 生成后的 app.js）

**首搜 gzip 字节**（p50/p90 按 382 条可路由查询统计）：

| 组成 | 字节 |
|---|---:|
| manifest | 6.3 KB |
| 分片 ×1（p50 / p90 估算） | ≈155 KB / ≈177 KB |
| aliases + confused | 91.7 KB + 0.9 KB |
| **合计 p50 / p90** | **253,875 B / 276,438 B** |
| 回退 core（2/384 条） | 3,671,586 B（= 现状 P1 首搜 3.78 MB） |
| 现状（core+aliases） | 3.78 MB → **P2 p50 ≈ 0.254 MB（-93.3%）** |
| `?legacy=1` | 6.06 MB（不变） |

**匹配延迟**（纯匹配，不含网络；Node v24 桌面）：

| 路径 | P50 | P90 | max |
|---|---:|---:|---:|
| 全量 core 线性扫描（接前） | 92.2 ms | 148.1 ms | — |
| 分片池线性扫描（首帧） | **2.68 ms** | **5.51 ms** | 21.9 ms |
| 分片 JSON.parse（每片一次，缓存） | 2.5 ms | — | 18.8 ms |
| core 到位后（搜索派生层，task-28） | ≈1.1 ms | ≈4.2 ms | — |

---

## 5. 354 三语回归 + 对拍

- **最终态不回归**：core 到位后 `render()`/`collectHits()` 与接入前完全同一路径（本轮未改匹配函数）。`bench_p2` 全量路径复现 **96.89% / 97.18%（354 条）**，与 task-28 基线一致；分类（single/salt/er/combo/dup_inn/zh_only）与语言分布同前。
- **首帧（core 前）分片池**：353 条可路由查询 Top-1/Top-5 92.63% —— exact/前缀/同字母桶模糊完整，缺的是跨桶 `contains`、别名全量品牌、跨桶模糊；core 到位后重渲恢复。已有 `res.partial` 提示与降级区块。
- **抽样对拍（DOM，同一构建）**：`?legacy=1` Lipitor 结果（前 2 行文本）与默认分片路径 core 到位后的最终结果**逐字一致**；CJK+CN、别名、拼音、typo、国家视图、ARTG 语义均通过断言。
- **DOM 15/15 断言通过**（`.tmp/dist-p2/dom_p2.json`）：

| # | 断言 | 结果 |
|---|---|---|
| 1 | 首次查询先拉 manifest | ✅（log: manifest, aliases, confused, shard-l, core, pinyin） |
| 2 | 分片在 core 之前请求 | ✅ shard@3 core@4 |
| 3 | Lipitor 分片阶段即出结果 | ✅ Atorvastatin… |
| 4 | CJK 查询（拼音首字母桶）分片出结果 | ✅ Amlodipine + Atorvastatin… |
| 5 | typo（同字母桶模糊）出结果 | ✅ Atorvastatin… |
| 6 | 别名查询最终命中（core 后） | ✅ Ibuprofen 151 brands |
| 7 | 拼音查询最终命中（core+pinyin 后） | ✅ 泰诺 / Acetaminophen…（Matchpinyin） |
| 8 | 国家视图 core 后生效 | ✅ `exact · country view` |
| 9 | 最终 core.json 已拉取 | ✅ |
| 10 | 分片阶段拉过 shard | ✅ |
| 11 | 无 JS 运行时错误 | ✅ |
| 12 | `?legacy=1` 只拉 index.json | ✅ |
| 13/14 | `?legacy=1` Lipitor / CJK+国家 出结果 | ✅ |
| 15 | **最终态与 `?legacy=1` 结果一致** | ✅ 逐字一致 |

---

## 6. 回退与降级矩阵

| 场景 | 行为 |
|---|---|
| 手动回滚 | URL `?legacy=1` → 旧 `index.json` 全量路径（DOM 验证）；彻底回滚用 `.tmp/dist-p2/build_before.py` 覆盖 `site/build.py` 重建（保留 UI P0/i18n/搜索 v2） |
| manifest 404/解析失败 | `startSearch` 捕获 → `loadIndex()` 拉 core（= 现状 P1 行为） |
| 分片 404/失败 | 同上回退 core；已加载的部分池不参与最终语义 |
| core 加载失败（分片已出结果） | 保留分片视图 + console.warn（不弹错误页）；用户仍可继续用 exact/prefix |
| 查询无可路由桶（2/384，首字符无桶） | 直接 `loadIndex()` 拉 core |
| `?q=` 深链 | 走分片快路径；core 后台补全 |
| 自动完成 | 分片阶段只扫已加载桶；core 后完整（不再抢跑 core） |
| 拼音 / ARTG / 国家视图 / 同成分 / 家族 | partial 阶段降级/延后，core 到位后恢复（拼音表仍懒加载） |
| 结果语义 | 最终态与接入前同一代码路径；首帧为「部分结果」提示，不静默展示错误结论 |

---

## 7. 发布影响与风险

- **dist 体积**：内层数据从 160.5 MB → 197.4 MB（+37 MB raw；分片与 core/index 同源重复）。GitHub Pages 1 GB 站点限制内；`deploy/publish.ps1` 既有检查（`index.json` ≥5 MB、文件数 ≥24k、无 0 字节）**仍通过**，但 gh-pages 每次发布需多传 ~5.5 MB gz 的分片，发布耗时会增加。
- **首帧语义窗口**：分片阶段 0.3–2 s（移动网络更长）内结果可能少于最终态，core 到位后列表/顺序会变化（有 `res.partial` 提示）；exact/前缀两类完整。若产品不接受，可用 `?shard=0` 开关全量回退（建议后续加）。
- **首搜体积** 254 KB 高于方案下限 0.1 MB：aliases 91 KB + 单片 ~155 KB。后续可（a）aliases 拆懒加载、（b）更细分片/前缀二分，预计可降到 ~120–150 KB。
- **分桶粒度**：首帧 `contains`（如 2 字中文片段跨桶）与拼音查询部分依赖 core；已按「core 后补全」降级，不阻塞首搜。
- **并发纪律**：构建独占 `site/build.py`；本轮新增 3 个 i18n 键（`res.partial`）与 APP_JS 分片块，交给 i18n 任务时请保留 `/* ── P2 分片… */` 与 `res.partial`。
- **数据漂移**：构建期间 `data/drugs.db` 可能被并行任务更新（分片/manifest 与 core 同源同一次构建，内部一致；跨版本发布注意缓存版本参数 `manifest.v`）。

---

## 8. 验收 / 复现

```powershell
$py   = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$node = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$env:SITE_OUT='.tmp\dist-p2\dist'; & $py site\build.py          # 构建（== done ==；manifest 68 shards）
& $node --check .tmp\dist-p2\dist\assets\app.js                 # 语法
& $node --max-old-space-size=8192 .tmp\dist-p2\bench_p2.mjs     # 首搜体积/延迟/354 回归 → bench_p2.json
$env:NODE_PATH=(Resolve-Path '.tmp\dist-search\node_modules').Path
& $node --max-old-space-size=8192 .tmp\dist-p2\dom_p2.mjs       # DOM 15 断言 → dom_p2.json
# 发布前另需：手动看一次 build 日志中的 manifest 行、抽查 /?legacy=1、首搜 Network 面板确认 manifest→shard→core 顺序
```

证据文件：`.tmp/dist-p2/{bench_p2.json, dom_p2.json, bench_p2.mjs, dom_p2.mjs, build_before.py, dist/}`；构建日志见任务执行记录。
