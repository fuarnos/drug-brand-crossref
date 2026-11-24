# v1.2.3 前置：sitemap index 门禁适配（`verify_live` / `ci_checks`）

> 工位：release ／ 任务板 `task-3` ／ 范围：**只改 `deploy/verify_live.py` + `deploy/ci_checks.py`**（未 commit、未构建、未发布）。
> 背景：v1.2.3 把 `sitemap.xml` 从单文件 170,435 URL 改成 **sitemap index + 4 分片**（每片 ≤50,000）。
> 这两处工具原来只会在单文件里数 `<loc>`，新结构下会误判（`<loc>` 只剩分片引用，总数变成 4）。

## 结论（先行）

| 项 | 结果 |
|---|---|
| `verify_live.py` | ✅ 识别 `<sitemapindex>`：逐片 GET 200 + 可解析 + 每片 ≤50,000 后求和，`sitemap-urls` 写「N shards / M urls」；新增 `sitemap-shards`；`<urlset>` 旧产物走旧逻辑 |
| `ci_checks.py` | ✅ `dist/sitemap.xml` 是 index 时求和、`sitemap_shards` 落 JSON；索引引用的每片必须存在于 dist；单片 >50,000 报 problems；旧单文件不变 |
| 自验 1：假 dist（5 例） | ✅ 求和 / 缺片 / 超限 / 旧单文件 / 越界引用，全部符合预期（见 §2） |
| 自验 2：`--fast`（现 dist = v1.2.2 单文件） | ✅ **13 项：PASS 8 / FAIL 0 / SKIP 5**，`dist-integrity` PASS「sitemap 170,435 URL」（向后兼容成立） |
| 自验 3：端到端 `verify_live`（本地 http.server，3 例） | ✅ index 正常 / 缺片 / 旧单文件，逻辑与文案均正确（见 §3） |
| `py_compile` | ✅ 两个文件通过 |

## 1. 改了什么

### `deploy/verify_live.py`（+68/−3）

- 新增常量 `SITEMAP_MAX_URLS_PER_FILE = 50_000`、`SITEMAP_LOC_RE`；新增纯函数 `sitemap_kind(text)`（`'index'` / `'urlset'` / `''`）与 `sitemap_shards(text)`（取分片 `<loc>` 列表），便于单独测。
- §7 改为双路径：
  - **index**：对每个分片 `<loc>` 走 `get()`（同源自动带 cache-buster；异源直连兜底）→ 要求 **HTTP 200**、含 `<urlset`、单片 `≤50,000` → 计数求和；
    - `sitemap-status`：index 本身 200（检查项名不变）；
    - **新增 `sitemap-shards`**：分片数 ≥1 且全部 200/可解析，明细写「N 片全部 200 且可解析（sitemap-1.xml 50,000 / … ）」，异常写「分片异常：sitemap-2.xml HTTP 404」；
    - `sitemap-urls`：**总数 ≥ `SITEMAP_MIN_URLS`（25,000）**，明细写「N shards / M urls（下限 25,000）」（检查项名不变，历史报告口径可比）。
  - **urlset（旧产物）**：`sm_text.count("<url>")`，明细加「单文件」字样；其余判定与原来完全一致。
- `robots` 检查不变（仍要求 `Sitemap:` 指 `sitemap.xml`）。模块 docstring 同步说明两种结构。

### `deploy/ci_checks.py`（+52/−3）

- 新增 `SITEMAP_MAX_URLS_PER_SHARD`、`SITEMAP_LOC_RE`、`_sitemap_shard_rel(loc)`（`<loc>` → dist 内相对路径，`..` 越界返回 `None`）。
- `check_dist()` 的 sitemap 段改为双路径：
  - **index**：逐片读 `dist/<分片>`，**缺一片即 `缺 sitemap 分片 <名>`**；分片不是 `<urlset>` 报错；单片 `>50,000` 报「超协议上限」；总数 < 25,000 报「N 分片合计 < 25,000」；`shard_count` 一并记录。
  - **urlset**：原逻辑逐字保留（`re.findall(r"<loc>")`）。
- 明细加「（N 分片合计）」（单文件时不加，保持旧文案）；`.tmp/ci/dist-integrity-*.json` 增加 `"sitemap_shards"` 键（`"sitemap"` 仍是**总数**），向后兼容旧读取方。
- `sitemap.xml` 仍在 `REQUIRED_DIST_FILES` 里（index 也必须存在）。

## 2. 自验 1：假 dist 打 `check_dist`（脚本 `.tmp/sm_ci_test.py`）

```
& $py -X utf8 .tmp\sm_ci_test.py
[A index/3-shards] sitemap=5 shards=3        sitemap-problems=['sitemap 仅 5 URL（3 分片合计 < 25,000）']
[B missing-shard]  sitemap=2 shards=2        sitemap-problems=['缺 sitemap 分片 sitemap-2.xml', 'sitemap 仅 2 URL（2 分片合计 < 25,000）']
[C over-50k]       sitemap=60000 shards=1    sitemap-problems=['sitemap 分片 sitemap-1.xml 有 60,000 URL（> 50,000 协议上限）']
[D legacy-urlset]  sitemap=30000 shards=0    sitemap-problems=[]
[E traverse]       sitemap=2 shards=2        sitemap-problems=['sitemap 分片引用非法: https://drugcrossref.com/../secret.xml', ...]
```

（A/B/C/E 的「仅 N URL」是假目录本身只有 5/2/2 条 URL，属预期；真 dist 170,435 时不会触发。）

## 3. 自验 2：`--fast`（现 dist = v1.2.2 单文件 sitemap，向后兼容）

```
& $py deploy\ci_checks.py --fast          # exit 0, 50.0 s
13 项：PASS 8 / FAIL 0 / SKIP 5（trilingual / check_data / ui-* / first-screen 在 --fast 记 SKIP）
[PASS] dist-integrity  302,107 文件 / 0 字节 0（fast-抽样：抽查 500 个）/ sitemap 170,435 URL / node 未安装跳过
.tmp/ci/dist-integrity-fast.json: {"sitemap": 170435, "sitemap_shards": 0, "problems": []}
```

结论：**没把旧产物打坏**——单文件路径判定与文案等价，`sitemap_shards=0` 明确区分「旧结构」。

## 4. 自验 3：端到端 `verify_live`（本地 `python -m http.server`，端口 8791，用后即杀）

```
== run1 index + 2 shards (2+1 urls)   checks=41
   sitemap-status  ok=True   :: HTTP 200
   sitemap-shards  ok=True   :: 2 片全部 200 且可解析（sitemap-1.xml 2 / sitemap-2.xml 1）
   sitemap-urls    ok=False  :: 2 shards / 3 urls（下限 25,000）      ← 假站只有 3 条，阈值按设计拦
== run2 index, shard-2 缺失           checks=41
   sitemap-status  ok=True   :: HTTP 200
   sitemap-shards  ok=False  :: 分片异常：sitemap-2.xml HTTP 404
   sitemap-urls    ok=False  :: 2 shards / 2 urls（下限 25,000）
== run3 旧单文件 urlset (3 urls)       checks=40
   sitemap-status  ok=True   :: HTTP 200
   sitemap-urls    ok=False  :: 3 个 URL（单文件 / 下限 25,000）       ← 无 sitemap-shards，证明走旧路径
```

（其他 34 项失败是本地假站没有首页/索引/资源导致的，与本次改动无关；服务已停止，`Get-CimInstance` 复查无残留 python 进程。）

## 5. 向后兼容结论

- **旧线上 / 旧 dist（单文件 urlset）**：`ci_checks` 与 `verify_live` 判定、检查项名、阈值全部不变；`verify_live` 不会多出 `sitemap-shards` 检查（checks 数 53 不变），历史报告口径延续。
- **新产物（index + 分片）**：`verify_live` 的 checks 会从 **53 → 54**（多一条 `sitemap-shards`），`sitemap-urls` 语义变成「分片求和」，门禁值仍是 25,000。
- **发布通道无需改动**：`sync_r2.ps1` 不特判 sitemap（grep 无命中），分片就是普通新文件、旧 `sitemap.xml` 同路径覆盖；`ci.yml` 也不引用 sitemap（跑的就是 `ci_checks.py`）。

## 6. 缺口 / 需要别人跟进的（不在本任务写入范围）

- **`db/nightly_metrics.py` 仍未适配**（第 221–224 行：`sitemap_urls = sm.read_text(...).count("<url>")`）。
  v1.2.3 上线后它会读到 **0**，而 `THRESHOLDS` 里有 `("pages.sitemap_urls", "drop_pct", 1.0, "sitemap URL 数下降")`（第 66/70 行）→ **夜间指标会误报回归**。
  建议 Lead 登一条 T 派给 backend（改法与 `ci_checks` 相同：index → 分片求和），本工位未越界改。
- 本段**未** commit、未跑 `site/build.py`、未跑 `sync_r2.ps1`（按 Lead 指示，等 v1.2.3 发布指令）。
- `reports/2026-11-24-v122-release.md` 已完成并交回（v1.2.2 已上线，verify 53/0/0）。
