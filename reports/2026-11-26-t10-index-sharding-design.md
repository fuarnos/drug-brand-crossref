# T10 索引按文字系统分片 —— 技术方案与现查评估（只出方案，不写实现）

- 日期：2026-11-26（北京，谷段）
- 工位：backend（任务 `task-5` B 段）
- 范围：**只做方案 + 现查评估**。未改 `site/`、`lib/`、`deploy/`、`db/`、`data/drugs.db`、`site/dist`；本文所有数字都可用 §2 的命令复现。
- 下一版实施建议归属：**frontend** 改 `site/build.py`（唯一站点源码写者）+ **release** 改 `deploy/` 门禁 + **backend** 出编码器规格与 `db/nightly_metrics.py` 同步。

---

## 1 结论（先行）

**推荐「方案 A：按文字系统把 `core.json` 拆成 latin / cjk / other 三片」**，`core.json` 保留一个版本周期做旧客户端兜底，第二版起只发分片。

为什么是它（三条硬理由）：

1. **护栏是被「单对象」卡住的，不是被总量卡住的**：现 `core.json` 67.96 MB raw / 13.32 MB gzip 已经吃掉护栏 **85.0% / 83.3%**（`CORE_RAW_RANGE` 11–80 MB、`CORE_GZ_RANGE` 2.5–16 MB）。拆 3 片后最大片 **39.29 MB raw / 8.73 MB gzip = 49.1% / 54.6%**，等于把「下个市场」的天花板抬高一倍以上；AGENTS §6 明确「下一次接近上限前必须先做索引按文字系统分片，而不是再调高」。
2. **代价可量化且很小**：三片合计 raw **+3.3%**、gzip **×1.045（13.93 MB）**，多 2 个请求，多 2–4 个 R2 对象/版（v1.2.5 单版 77,235 PUT，增量可忽略）；**首屏 / 首搜一个字节都不变**（首搜仍走 `manifest + ≤3 个 shard`，254,051 B gzip）。
3. **方案 B/C 结构上不成立**（§4）：名字键（362,502 行）本身跨市场、跨语言，按市场或按 pid 前缀切会把同一行复制到多片，请求数与总量都变差；只有「按行的文字系统」是一行一片、不复制。

**工程量：约 1.5–2 人日 / 1 个版本**（frontend 0.5–1 天改 build.py 编码 + 客户端合并，release 0.5 天改 5 处门禁，联合验收 0.5 天）。
**一句话风险**：拆分后**必须保住行序**（客户端 tie-break 顺序会变）与**旧客户端兼容**——方案里用 `ord` 列 + `core.json` 双写一版解决，回滚成本 = 一个 `BUILD_CORE_SPLIT=0` 开关。

> 明确一句边界：**拆片本身不减少用户下载量**（要聚合视图的人仍要拿全三片，甚至 +4.5%）。真要降移动端流量，是 T10-b「聚合切片」（§9）。本版先解护栏，T10-b 随后。

---

## 2 现查基线（数字 + 复现命令）

> 探针：`.tmp/t10_probe.py`、`.tmp/t10_split_measure.py`（`.tmp/` 不入库；关键代码见附录 A/B）。全部只读 `site/dist`。

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\t10_probe.py            # core 体积 / 列开销 / 文字系统分布 / 分片实测
& $py .tmp\t10_split_measure.py    # 2/3/4 片真实 raw+gzip（写到 .tmp/t10-parts/）
```

### 2.1 核心索引现状

| 项 | 数值 | 说明 |
|---|---|---|
| `site/dist/data/idx/core.json` raw | **67,963,821 B（67.96 MB）** | gzip/raw = 0.196 |
| 同文件 gzip -9 | **13,321,117 B（13.32 MB）** | 护栏上限 16 MB → **83.3%** |
| raw 护栏占用 | **85.0%** | 上限 80 MB（`deploy/verify_live.py:76`） |
| 行数 `n` | **362,502** 个名字键 | core v2（`CORE_VERSION=2`） |
| 列数 / 厂家表 / 稀疏 q | 28 列 / `mk` 14,759 条 / `q` 163 行 | |
| 列开销账 | 平铺 29,506,602 + 字典值 9,705,389 + 字典下标 22,477,213 + `mk` 827,861 + 其它 5,446,756 = **67,963,821** | 账目自洽（探针 §「账目核对」） |

### 2.2 行按「k 首字符」的文字系统分布（决定切片边界）

| 首字符区块 | 行数 | 占比 |
|---|---|---|
| lower a-z | 217,685 | 60.1% |
| **Hangul（韩文）** | **106,342** | 29.3% |
| CJK ideograph（汉字） | 28,479 | 7.9% |
| Kana（日文假名） | 8,656 | 2.4% |
| digit | 940 | 0.3% |
| punct/other | 388 | 0.1% |
| Greek / Latin-1 Ext | 8 / 4 | ≈0% |

**要点 1**：`latin` 必须按 **Unicode 区块**判（ASCII a-z + A-Z + U+00C0–U+024F + U+1E00–U+1EFF），不能按 ASCII 判——现有 `encode_shards()` 的 `_shard_bucket()`（`site/build.py:21688-21700`）把**大写 A-Z、带音标拉丁、Hangul 全归到 `other`**，直接照抄会把 29.3% 的韩文错切进 other。
**要点 2**：`cjk` 组 = 汉字 + 假名 + 谚文（143,477 行）；它自己就能压（gz/raw 0.162），因为韩文音节重复度高。

### 2.3 拆片实测（真做出来再量，不是估算）

`& $py .tmp\t10_split_measure.py` → 输出（节选）：

```
core.json raw=67,963,821 gzip9=13,321,117 n=362,502

── 3 片 latin / cjk / other
  core-latin.json  rows= 217,689  raw= 39,293,641 B ( 39.29 MB)  gzip9= 8,732,035 B ( 8.73 MB)  gz/raw=0.222
  core-cjk.json    rows= 143,477  raw= 29,821,219 B ( 29.82 MB)  gzip9= 4,837,663 B ( 4.84 MB)  gz/raw=0.162
  core-other.json  rows=   1,336  raw=  1,108,946 B (  1.11 MB)  gzip9=   356,760 B ( 0.36 MB)  gz/raw=0.322
  合计 raw=70,223,806 B (70.22 MB, +3.3%)  gzip9=13,926,458 B (13.93 MB, 1.045× core)

── 2 片 latin / 非latin   ：raw 69,398,102 B (+2.1%)  gzip9 13,644,905 B (1.024×)
── 4 片 latin / han / hangul / other
  core-hangul.json rows= 106,342 raw=22,636,940 B  gzip9= 3,493,292 B
  core-han.json    rows=  37,135 raw= 6,657,314 B  gzip9= 1,617,741 B
  合计 raw=69,696,841 B (+2.5%)  gzip9=14,199,828 B (1.066×)
校验：各级分片行数合计 = core.n，全部可 JSON 解析
```

| 方案 | 片数 | 最大片 raw / 占 80 MB | 最大片 gzip / 占 16 MB | 合计 gzip vs 现 core |
|---|---|---|---|---|
| 现状（单文件） | 1 | 67.96 MB / **85.0%** | 13.32 MB / **83.3%** | 1.000× |
| 2 片 latin / 非latin | 2 | 39.29 MB / 49.1% | 8.73 MB / 54.6% | 1.024× |
| **3 片 latin / cjk / other（推荐）** | 3 | 39.29 MB / 49.1% | 8.73 MB / 54.6% | 1.045× |
| 4 片 latin / han / hangul / other | 4 | 39.29 MB / 49.1% | 8.73 MB / 54.6% | 1.066× |

- 「合计 raw +3.3%」= 字典重复（每片各自保留用到的字典值，实测重复 **686,908 B = 7.1% 字典字节**）+ `mk` 表整份保留（本次实测是上界，真实施可以按片重编号压掉一部分）。
- **4 片意义不大**：latin 仍是最大片（39.29 MB），只把 cjk 拆成 han/hangul，换来总计 +6.6% 和 4 个请求；除非**下一个市场是日本全量**（han 会涨）再考虑。

### 2.4 客户端首屏 / 首搜成本（拆分前的现状）

| 组成 | raw | gzip -9 |
|---|---|---|
| `index.html` | 220,472 | 57,418 |
| `assets/app.js` | 191,952 | 70,590 |
| `assets/i18n.js` | 608,007 | 205,814 |
| `assets/style.css` | 110,531 | 32,144 |
| **首屏合计 `first_screen_gz`** | | **365,966**（= 夜间指标现数） |
| `data/idx/manifest.json` | 51,108 | 13,554 |
| 1 个 shard（179 片的中位） | ~1.1 MB | 138,856 |
| `data/aliases.json` / `data/confused.json` | 1,068,846 / 3,552 | 100,520 / 1,121 |
| **首搜合计 `first_search_gz`** | | **254,051**（= 13,554 + 138,856 + 100,520 + 1,121） |
| `data/idx/core.json`（**后台/按需**） | 67,963,821 | **13,321,117** |

**结论：core 不在首屏、也不在首搜路径里**——它是「用户要聚合视图（换国家 / 同成分 / 品牌家族 / 拼音重试）」时的兜底全量（`site/build.py:12525-12588` 的 `CORE_BG` 门控：9 s 安静期 + `requestIdleCallback` + 省流/2G/3G 不预取）。所以拆片**不该、也不会**动首屏与首搜指标；反过来，任何声称「拆片降低首屏」的说法都不成立（这点写进验收，防止有人拿错指标邀功）。

### 2.5 现有分片体系（不要重复造）

| 产物 | 作用 | 现状 |
|---|---|---|
| `manifest.json` | 分片目录（`buckets` / `cjkInitials` / `core{ f, bytes }` / `v`） | 51,108 B raw / 13,554 B gz，179 片 |
| `shard-<bucket>-<n>.json` | **首搜**用：按首字母/拼音首字母/other 分桶，每片 ~1.1 MB raw | 179 片合计 166,739,769 B raw / 23,234,803 B gz |
| `core.json` | **全量兜底**（聚合视图） | 67.96 MB / 13.32 MB |
| `detail-*.json` | 行展开时懒加载 | 74 个文件 |
| `pinyin.json` / `cats.json` / `atc-ing.json` / `atc4-forms.json` | 拼音、类别、ATC 词表 | 各自懒加载 |

即：**「首搜分片」早已有，「全量核心按文字系统分片」没有**——T10 要补的正是后者。

---

## 3 生成与消费路径（代码位置，按 HEAD 行号）

| 环节 | 位置 | 现状 |
|---|---|---|
| 条目来源 | `site/build.py:22818` `entries = load_index(db)` | SQL 无 `ORDER BY` → 行序 = SQLite 自然序（**不是 k 排序**） |
| 编码器 | `site/build.py:21494-21537` `encode_core()`；`CORE_FIELDS` 21462、`CORE_VERSION=2` 21454 | 列式 + 字典编码，v2 用 `fl` 位掩码（`t/nc/eo`）与 `ux/uxv`（`u` 由客户端推导） |
| 写盘 | `site/build.py:22826-22829` | `data/idx/core.json` 单对象 |
| manifest | `site/build.py:21716-21718`（`encode_shards` 里写 `core{ f, bytes }`）、22848-22852 | 已留 `core` 字段但**客户端没用** |
| 版本号注入 | `site/build.py:22729` | `.replace("data/idx/core.json", "data/idx/core.json?v=BUILD_V")`（同时替换 manifest） |
| 客户端加载 | `site/build.py:12371-12390` `loadMainIndex()`；`12322-12367` `decodeCore()`；`CORE_V=2`（12314） | `fetch core.json` → 校验 `c.v` → 解码；失败再 `legacy-mini.json` → 仍失败交错误 UI |
| 客户端后台/按需 | `12525-12588`（`CORE_BG` / `ensureCoreInBackground` / `ensureIndexOnDemand`） | 9 s 安静期 + 空闲回调 + 网络门控 |
| 分片选择 | `12479-12523`（`shardKeyOf` / `shardsForQuery` / `loadShardedIndex`） | 首搜取 ≤3 片 |

**与 `core.json` 相关的门禁/工具（7 处，全部要一起改，见 §5）**：

| 文件 | 断言 | 现状问题 |
|---|---|---|
| `deploy/verify_live.py:75-76, 179-203, 382-415` | `core-json-http` / `core-json-size`（gzip 2.5–16 MB、raw 11–80 MB）/ `core-json-gzip` / `core-size-vs-dist` | 只认单对象；`local_core_gz()` 只读 `core.json` |
| `deploy/verify_live.py:50, 271` | `homepage-no-index-preload`（正则 `rel="preload"…(index|core)\.json`） | 分片后要扩到 `core-` |
| `deploy/ci_checks.py:73-81, 391-393` | `REQUIRED_DIST_FILES` 含 `data/idx/core.json`；`CORE_MIN_BYTES = 10,000,000` | 分片后 `core.json` 可能消失 → 直接 FAIL |
| `deploy/check_core_fields.py:53-59` | `REQUIRED_COLS=("t","nc","eo")` + `GZIP_MAX_BYTES=12,000,000` | **已经过期**：core v2 把 t/nc/eo 合成 `fl`、`u` 由 k 推导 → 现跑 **4 项 FAIL**（§6.1） |
| `deploy/ui_sort_smoke.py:714-718` | 有 `core.json` 才跑，否则 SKIP | 分片后永远 SKIP |
| `db/nightly_metrics.py:244, 257-276, 405-409` | `core_gz`（rise 5%）/ `index_gz`（**过时**，见 T17 报告 §3.2） | 分片后 `core_gz` 会变 0 → 误报「缺失」 |
| `render_dashboard.py:128` | 读 `core.json` 大小做看板 | 分片后要改求和 |
| `tests/trilingual/` | 只读 DB（不碰 `core.json`） | **无需改**（已 grep 确认） |

---

## 4 候选方案对比

> 判定口径（派单要求）：客户端改动量 / 首屏请求数与体积 / SEO / 门禁改动 / A/A′ 确定性 / 回滚成本。

### 方案 A（推荐）按文字系统切行：latin / cjk / other

- **做法**：`encode_core()` 拆成 `encode_core_parts()`，按 `k[0]` 的 Unicode 区块归组，每组独立跑现有列式编码（字典各自重编号），写 `data/idx/core-<group>.json` + manifest `cores[]`。
- 客户端改动量：**小**。`loadMainIndex()` 从「fetch 1 个」改成「读 manifest（已经在用）→ 并行 fetch N 个 → 各自 `decodeCore` → 按 `ord` 合并」；`decodeCore` 本身**一行不改**。
- 首屏请求/体积：**不变**（core 不在首屏/首搜）；聚合视图从 1×13.32 MB 变 3×~4.6 MB（并行）→ 合计 **13.93 MB（+4.5%）**，时延通常更好（3 个并行 + 分片可享用现有 HTTP/2 多路复用）。
- SEO：**无影响**（JSON 不在 sitemap；`robots.txt` 是 `Allow: /`；`data/*.json` 不被索引也不被 hreflang 引用）。
- 门禁改动：中（5 个文件，见 §5；都是「单对象 → 多对象求和/逐片断言」的机械改）。
- A/A′ 确定性：**可保持 0 差异**——分组是纯函数、组名排序固定、`json.dumps` 参数不变；风险点是行序（见 §6.2），用 `ord` 列解决。
- 回滚成本：**极低**——`build.py` 加开关 `CORE_SPLIT=0` → 退回单文件；`core.json` 过渡期双写，回滚不需要动线上对象。

### 方案 B 按市场分片（18 市场）

- 结构问题：`core` 的行是**名字键**，一行聚合多国产品（`c` 列是数组）。按市场切必须把一行复制到多片 → 重复量 ≈ 国家数/平均国家数（粗估 2–3×），总量与请求数一起恶化；且「换国家」视图本来就要跨市场数据。
- 首屏请求：聚合视图可能要 **18 个请求**，HTTP 开销和 R2 PUT（每版 18 个对象）都更差；SEO 无影响；门禁改动更大（要断言 18 片 + 市场名单漂移）。
- **不采用。**

### 方案 C 按 pid / 名字前缀固定桶（复用 `shard-*` 形态）

- 结构问题：pid 是产品维度，`core` 行是名字键；按前缀切等于「把首搜分片再做一遍」，聚合视图仍要全量 → 只是把 1 个大对象拆成 179 个，请求数爆炸（179 个并发 fetch）。
- 好处是客户端选择逻辑现成（`shardsForQuery`），但**对聚合视图无效**（聚合必须扫全部行）。
- **不采用**（可作为「首搜」的既有方案保留，不需要重做）。

| 维度 | A 文字系统 | B 市场 | C 前缀桶 |
|---|---|---|---|
| 行复制 | 无（一行一片） | 有（多国行被复制） | 无 |
| 片数 | 3 | 18 | 179 |
| 最大片 raw | 39.29 MB | 取决于最大市场 | ~1.1 MB |
| 聚合视图请求数 | 3 | 18 | 179 |
| 合计 gzip | 1.045× | ≥1.3×（重复 + 字典重复） | ≈1.15×（字典重复 ×179） |
| 客户端改动 | 小（合并 + ord） | 中（市场集合 + 合并） | 大（179 并行 + 合并） |
| 门禁改动 | 中 | 中大 | 中大 |
| 回滚 | 开关 + 双写 | 同左但更重 | 同左但更重 |

---

## 5 方案 A 的设计细节（下一版可直接照做）

### 5.1 产物格式

```
data/idx/core.json          # 过渡期保留（旧客户端兜底），第 2 版起停写
data/idx/core-latin.json    # 组名固定 3 个：latin / cjk / other（排序写盘，保证确定性）
data/idx/core-cjk.json
data/idx/core-other.json
data/idx/manifest.json      # 新增 cores: [{g:"latin", f:"data/idx/core-latin.json", n:217689, bytes:39293641}, ...]
                            #      保留 core:{f,bytes}（旧客户端 + 旧门禁读它）
```

- 每个 `core-<g>.json` **与现有 `core.json` 同格式**（`{v,n,mk,cols,q}`），只是行子集；`decodeCore()` 不改。
- **新增 `ord` 列**（`cols.ord`，普通列）：该片第 i 行的**全局原始下标**。客户端合并时 `IDX[ord[i]] = row`，得到与今天**逐行同序**的 IDX（这一点是「不可察觉」的关键，见 §6.2）。
  - 体积代价：362,502 个整数，实测口径 ~+2.2 MB raw / 约 +0.5 MB gzip（可在实施时量；若嫌大，改用 §5.4 的 RLE 方案）。
- 分组函数（纯函数，写进 `site/build.py`）：

```python
def _script_group(key: str) -> str:          # 与探针 group_of_key 同口径
    ch = (key or "")[:1]
    if not ch: return "other"
    cp = ord(ch)
    if ("a" <= ch <= "z") or ("A" <= ch <= "Z") or 0xC0 <= cp <= 0x24F or 0x1E00 <= cp <= 0x1EFF:
        return "latin"
    if (0x3400 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF      # 汉字
            or 0x3040 <= cp <= 0x30FF                          # 假名
            or 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF):  # 谚文
        return "cjk"
    return "other"
```

### 5.2 客户端合并（`loadMainIndex`）

```
manifest.cores 存在 → Promise.all(cores.map(f => fetchJSON(f.f + ver)))
                   → 每个跑 decodeCore（复用现有函数）
                   → const IDX = new Array(nTotal); 逐片按 ord 落位
                   → 校验：落位数 == nTotal，否则 throw（走现有错误 UI）
manifest.cores 不存在（旧 dist）→ 原路径 fetch core.json（保持不变）
```

- `MANIFEST` 本来就在首搜时加载（`fetchManifest`），**不新增请求**去拿目录。
- 失败降级顺序不变：`core.json` → `legacy-mini.json` → 错误 UI；分片失败时**先退回 `core.json`**（过渡期它还在）。

### 5.3 写盘与开关

- `encode_core_parts(entries)` 内部按 `_script_group` 分桶 → 每组 `encode_core(subset)`（复用现函数，输入是子集 entries）。
- 构建开关（默认开，回滚用）：`CORE_SPLIT=0` → 只写 `core.json`（今天的行为）；`CORE_SPLIT=1`（默认）→ 写 3 片 + **双写** `core.json`；第二版默认改成 `CORE_DUAL_WRITE=0`。
- 打印行要加：`core parts: latin 39.29 MB / cjk 29.82 MB / other 1.11 MB（合计 +3.3%）`，方便 report 里抄。

### 5.4 可选的省字节优化（本次不必做）

- `ord` 用 **RLE**：manifest 里记 `coresRuns: [["latin",120],["cjk",3],…]`（行序如果大致按块聚，run 数很少），客户端按 run 消费计数交错取行 → 省掉 ~2 MB raw。**要在实施时先量 run 数**（现值未知，属实施第一步）。
- `mk` 表按片重编号（当片引用不到一半厂家时可省 ~0.4 MB）。

---

## 6 A/A′ 确定性、A/B 增量发布、行序

### 6.1 A/A′（同输入两次构建 0 差异）

- 分组纯函数 + 组名排序固定 + `json.dumps(..., separators=(",",":"), ensure_ascii=False)` 参数不变 → 3 个分片字节级可复现。
- 现有 `BUILD_V` 是内容哈希（`_compute_build_v`），分片文件也进 dist，不引入时间戳。
- **验收时必须实跑两次构建并 diff**（`site/build.py` 已有的 A/A′ 流程），分片文件必须 0 差异。

### 6.2 行序（**本方案最大的隐性坑**）

- 现在 `IDX` 的行序 = `load_index()` 的 SQLite 自然序（没有 `ORDER BY`）；`render()` 的同分 tie-break、`inCountry()`/同成分列表顺序都建立在「顺序与旧 index.json 一致」上（`site/build.py:21439-21440` 注释写死了这一点）。
- 分片后若简单 concat（latin + cjk + other），**行序会变** → 同分结果顺序可能变，trilingual / ui-sort 可能报差异。
- 解决：`ord` 列（§5.1）→ 合并后与今天**逐行同序**；验收里加一条「合并后 `IDX` 与 `core.json` 解码结果逐行 `JSON.stringify` 相等」。

### 6.3 A/B 版本差分与 R2 预算

- 每版变化文件：`core.json`（双写期）+ 3 个 `core-*.json` + `manifest.json` + `app.js`（客户端改动）+ 顶层页（引用 `app.js?v=`）→ 预计 **+4~6 个文件**，远低于「常规版 ≤500 文件 / planned ≤1,000」。
- `rclone sync` 会**删除** dist 里不存在的对象：第 2 版停写 `core.json` 时，它会从 R2 消失 → 旧客户端 404。两种处理：
  1. **推荐**：第 2 版前给 `deploy/sync_r2.ps1` 加一条**精确** `--exclude data/idx/core.json`，保活到「过渡期结束日」（照 `data/legacy_assets.json` 的 pattern 精神，但该文件只管 `assets/`，需要单独一处，**属 release 工位**）；
  2. 或一直双写（每版多 1 个 68 MB PUT，占 1 次 PUT，成本≈0，但对象长期存在）。
- R2 PUT 量级：v1.2.5 = 77,235 PUT（当月累计 486,413 = 48.6%），本改动 **+4~6/版**，对免费额度无感；存储 +70 MB（R2 免费 10 GB 量级，可忽略）。

### 6.4 SEO 与线上可发现性

- sitemap / robots / hreflang / canonical **完全不动**（`core*.json` 不在 sitemap，`robots.txt` 是 `Allow: /`）。
- 新增 3 个可公开访问的 JSON 路径（`/data/idx/core-*.json`）——不被索引、不被引用为 canonical，无 SEO 风险；若担心被爬，可在 `robots.txt` 加 `Disallow: /data/`（现无，**不在本方案默认动作**，需 Lead 拍板）。
- `homepage-no-index-preload` 门禁继续有效：分片后正则要覆盖 `core-`。

---

## 7 门禁与工具改动清单（逐文件、逐项）

| # | 文件 | 改什么 | 验收判据 |
|---|---|---|---|
| 1 | `deploy/verify_live.py` | ① `CORE_GZ_RANGE` / `CORE_RAW_RANGE` 语义改为**逐片**（或对「片内最大」判定）；② 新增 `core-parts`：manifest 里的每个 `cores[].f` 必须 HTTP 200 + `content-type: json`；③ `core-size-vs-dist` 逐片对比；④ `PRELOAD_IDX_RE` 扩到 `core-` | 发布后 verify 的 core 相关项全 PASS；片数 = manifest 声明数 |
| 2 | `deploy/ci_checks.py` | `REQUIRED_DIST_FILES` 由 `data/idx/core.json` 改为「`manifest.json` + manifest 里每个 cores 文件」（或双写期两者都要）；`CORE_MIN_BYTES` 改为**逐片下限**（如 ≥1 MB）+ 合计下限 | 全量 dist-integrity PASS，且能抓「漏写一片」 |
| 3 | `deploy/check_core_fields.py` | ① `REQUIRED_COLS` 改 v2：`fl` 存在 + `ux/uxv` 存在（`t/nc/eo` 由 `fl` 拆）；② `GZIP_MAX_BYTES` 12 MB → **16 MB**（与 verify_live 对齐）；③ 支持逐片检查（`--dist` 时遍历 cores） | 该脚本从「4 FAIL」变 **0 FAIL**；再接进 `ci_checks` |
| 4 | `deploy/ui_sort_smoke.py` | 判「产物完整」的条件从 `core.json` 改为 `manifest.cores` 或任一 `core-*.json` | 不再因分片 SKIP |
| 5 | `db/nightly_metrics.py` | `sizes.core_gz` 改「各片 gz 之和」+ 新增 `sizes.core_parts`（片数）；顺手把过时的 `index_gz` 换成 core/parts（T17 报告 §3.2 = T20） | 不再报「core 缺失」；`core_gz` 与真值一致 |
| 6 | `render_dashboard.py` | `:128` 读 core 大小改求和 | 看板数字与 dist 一致 |
| 7 | `deploy/sync_r2.ps1` | （第 2 版才需要）精确 `--exclude data/idx/core.json` 保活 | `-DryRun` 里 `core.json` 不再出现在 Deleted |

---

## 8 风险与回滚

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 行序变化导致同分结果顺序变 | 中 | 中（用户可见，测试可能报差异） | `ord` 列合并；验收加「逐行相等」断言 |
| 旧客户端（缓存页）请求 `core.json` 404 | 中 | 高（错误 UI） | 过渡期**双写** `core.json` ≥1 版；第 2 版前加 sync `--exclude` 保活 |
| 漏写 / 写坏一片（build 中途失败） | 低 | 高（聚合视图全挂） | `ci_checks` 加「manifest 声明的片必须存在且 ≥1 MB」；`check_core_fields` 接进 CI |
| 字典重复/`mk` 复制导致总量虚高 | 高（已知） | 低（+3.3%） | 已实测上界；可选 §5.4 优化 |
| 三片并行拉取在弱网下触发超时 | 低 | 中 | 现有 `fetchJSON` 无重试 → 失败退 `core.json`（双写期）；后续可加 1 次重试 |
| 门禁口径改错（把「合计」当「单片」） | 中 | 中（误放行大对象） | 门禁同时断言「逐片」和「合计」两档，报告写清 |

**回滚**：① 单版内：`CORE_SPLIT=0` 重构建 + 重发布 → 回到今天的产物（`core.json` 一直在写，客户端也有旧路径）；② 已发布后：`sync_r2.ps1 -DryRun` 预演上一版产物 → 只回传变化文件；③ 最坏：`deploy/legacy_assets.json` 里已废弃的 hashed 资源保活机制**不适用**于 data/，所以「双写」是必须项，不能省。

---

## 9 实施步骤清单（下一版照做，1.5–2 人日）

**Step 0（0.2 h，backend，只读）**：跑 §2 探针，把 3 片实测数字贴进实施单；同时统计 `ord` RLE 的 run 数，定「`ord` 列 vs RLE」。
**Step 1（2–3 h，frontend）**：`site/build.py`
  1. 加 `_script_group()`（§5.1）；
  2. 加 `encode_core_parts(entries)`：分组 → 复用 `encode_core` → 加 `ord` 列；
  3. 写盘 `core-<g>.json`（组名排序）+ 双写 `core.json` + `CORE_SPLIT` / `CORE_DUAL_WRITE` 开关；
  4. `manifest` 增 `cores[]`（保留 `core`）；
  5. 客户端 `loadMainIndex()` 支持 `manifest.cores` 合并（含 `ord` 落位 + 总数校验），旧路径不动；
  6. 打印分片体积行；`?v=` 替换逻辑覆盖新文件名。
**Step 2（0.5 h，frontend 自验，**临时目录**）**：`$env:SITE_OUT='.tmp/t10-build'; & $py site/build.py` → 量 3 片 raw/gz、跑一次 A/A′（第二次构建 diff 0）。
**Step 3（2 h，release）**：改 §7 的 5 个门禁 + 2 个工具（verify_live / ci_checks / check_core_fields / ui_sort_smoke / nightly_metrics / render_dashboard）；`check_core_fields.py` 从 4 FAIL → 0 FAIL 并把 `GZIP_MAX_BYTES` 与 verify_live 对齐。
**Step 4（1 h，联合验收）**：本地预览临时产物（`serve.py` 写死 `site/dist`，预览临时产物要用 `& $py -m http.server 8000 --directory .tmp/t10-build`）→ 9 语各抽 1 条 → 覆盖「换国家 / 同成分 / 品牌家族 / 拼音重试」四个聚合块；旧客户端兼容模拟（用上一版 dist 的 `app.js` 指向新 dist 的 data 目录，`core.json` 双写在 → 必须照常工作）。
**Step 5（release，发布）**：CHANGELOG 一节 → 构建 `== done ==` → `sync_r2.ps1`（`-DryRun` planned 应 ≈ 当前 78 + 5）→ `verify_live --expect-version vX.Y.Z` **0 failures** → tag/Release。
**Step 6（第 2 版）**：`CORE_DUAL_WRITE=0` + `sync_r2.ps1` 精确 `--exclude data/idx/core.json`（30 天保活）→ 之后再删 exclude。

---

## 10 验收口径（必须全过才算做完）

1. **A/A′ 确定性**：同输入两次构建，`site/dist` **0 差异**（含 3 个 `core-*.json`）。
2. **A/B 版本差分**：常规版 **≤500 文件**、`-DryRun` planned **≤1,000**（本改动 expect +4~6）；长尾六类页面 **0 差异**。
3. **逐片护栏**：每片 raw ≤80 MB / gzip ≤16 MB；且合计 raw 与实测基线偏差 ≤10%（本次实测 +3.3%）。
4. **数据等价**：`manifest.cores` 合并后的 `IDX` 与现 `core.json` 解码结果**逐行 `JSON.stringify` 相等**（行序 + 字段全等）。
5. **首屏/首搜不回归**：`first_screen_gz` = 365,966 B（±1%）、`first_search_gz` = 254,051 B（±1%）；`homepage-no-index-preload` PASS。
6. **三语 / 九语抽查**：zh / en / es 各 3 条查询（含 1 条中文名、1 条韩文名、1 条拼音首字母）结果行数与改前一致；四个聚合块可用。
7. **旧客户端兼容**：上一版 `app.js` + 新 dist data → 正常出结果（或明确只在双写期保证）。
8. **门禁全绿**：`deploy/ci_checks.py` 13 PASS / 0 FAIL；`verify_live` 0 failures（含新增片断言）；`check_core_fields.py` 0 FAIL；`tests/trilingual/run_tests.py` 照旧通过（不受影响）。
9. **发布报告**写「本次 PUT / 当月累计 / 占免费额度 %」+ 片的 raw/gz 实测表。

---

## 11 §12「先找现成工具」检索结论

> 检索时间 2026-11-26。仓库硬约束：**无 npm 构建链**、静态构建、内联资源、`vendor/` 只允许离线参考、不许新增依赖到 `site/build.py`。

| 候选 | 许可 | 是什么 | 结论 |
|---|---|---|---|
| **FlexSearch**（`flexsearch@0.8.212`） | Apache-2.0（上游 LICENSE） | 浏览器全文倒排索引；gzip 4.5–16.3 KB 三种构建 | **不用**：它是「文本 → 文档」倒排，我们的行是结构化记录（成分/规格/国家/厂家），已用列式 + 字典编码压到 0.196；换成倒排反而更大、还要重写渲染层。[npm](https://www.npmjs.com/package/flexsearch) |
| **MiniSearch** | MIT | 同上（in-memory 全文索引） | **不用**：同因；且要新增 npm 依赖 |
| `fzstd` / `brotli-wasm` 等 WASM 解压器 | MIT | 客户端解 zstd/brotli | **不用（本版）**：Cloudflare 已对 JSON 走 gzip；改 br/zstd 只能省 10–25% 传输，却要引入 20–50 KB WASM + 解压 CPU + 改 `verify_live` 传输断言，收益远小于「按需只拉一片」。[压缩库对比](https://derodero24.github.io/comprs/) |
| 静态大 JSON「分片 + 懒加载」范式 | 通用范式 | 多文件 + manifest 目录 + 并行 fetch | **已在用**：本仓 `manifest.json` + `shard-*` + `detail-*` 就是这套；T10 只是把同一范式用到「全量核心」上。[参考](https://skills.rest/skill/big-static-data-frontend-kuschikuschbert) |

**结论**：没有现成库能替我们做「列式 + 字典 + 按文字系统切行」这件事；沿用现有 `encode_core` + `manifest` 范式是唯一不破坏「无依赖 / 首搜 254 KB」两条硬约束的路线。

---

## 12 未做 / 后续（T10-b 提案，本版不做）

1. **聚合切片替代全量 core（真正的流量优化）**：把「换国家 / 同成分 / 品牌家族」改成服务端预生成的小切片（例如按 substance_id 前 2 字符分桶、按国家分文件），客户端只拉命中所需的 1–2 个切片（预计 5–50 KB gzip/片），彻底不拉 13.3 MB。工程量 2–3 人日，需要新产物 + 新门禁。
2. **触发条件（写进队列）**：下个市场入库后，若「core 合计 raw > 100 MB」或「最大单 ≤ 60% 护栏被突破」，先做 T10-b 再考虑 4 片。
3. **不做的**：不把 `core.json` 改成按需 HTTP Range 分段（需服务端支持，R2 静态对象 + CF 缓存不可控）；不给 JSON 加 br 预压缩（见 §11）。

---

## 附录 A：探针 `.tmp/t10_probe.py` 关键逻辑

- 读 `core.json` → 按列形态分类（`dict` / `flat` / `dict-sparse`=`uxv` / `flat-sparse`=`ux`）；
- 按 `k[0]` 的 Unicode 区块给每行打 `latin/cjk/other/digit/greek`，累计「内容字节」（各行取值 JSON 长度）与「该类用到的字典值集合」；
- 字典重复 = Σ每类字典值字节 − 全局字典值字节（实测 686,908 B / 7.1%）；
- 分片实测走 `.tmp/t10_split_measure.py`：按组过滤列 → 字典重编号 → `json.dumps` 原样落 `.tmp/t10-parts/` → `gzip -9` 量体积（**这就是「方案 A 的真实数字」，不是外推**）。

## 附录 B：复现命令与产物

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\t10_probe.py         2>&1 | Tee-Object .tmp\t10_probe.out.txt
& $py .tmp\t10_split_measure.py 2>&1 | Tee-Object .tmp\t10_split_measure.out.txt
# 产物：.tmp/t10-parts/core-{latin,cjk,other}.json（2/4 片方案会覆盖同名文件，重跑顺序见脚本）
```

> 本报告**未**：改 `site/build.py` / `deploy/*` / `db/*` / `data/**` / `site/dist/**`，未 build、未发布、未 commit。
