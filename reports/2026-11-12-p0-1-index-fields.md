# P0-1 定位报告：`core.json` 缺 `t` / `nc` / `eo` 三列 → 搜索结果显示「无商品名」

> 工位：search-alias（检索与评测）· 2026-11-12 · **只读定位，未改任何代码 / 产物 / 数据库**
> 对手：`docs/下一轮优先级-20261111.md` §1 P0-1「搜 `Tylenol`：初步结果正常显示品牌；完整索引加载后大量结果变成「无商品名」，原名退到「命中名」里」
> 复现对象：`site/dist` 现存产物（v0.11.1，构建于 2026-11-10 13:51）

---

## 0. 结论先行

1. **根因是一处漏字段，不是「两套索引各有一套字段映射」**。分片把 `load_index()` 的条目**原样**序列化（字段齐全），
   `core.json` 走列式编码 `encode_core()`，那里的字段清单是**手写元组**，从 v0.9.0 起新增的
   **`t`（是否 trade 名）、`nc`（名称层/无成分）、`eo`（Export Only）** 三个字段没被加进去。
2. 前端 `brandHTML()` 的判定是 `if (e.t !== 1)` → core 解码后 `e.t === undefined` → **所有行都走「无商品名 + 命中名」分支**。
   分片阶段 `e.t` 在，所以同一次查询前半程正常、后半程翻转。**这不是分片 vs core 的映射不一致，是 core 少了一列。**
3. 影响：索引 **196,200 行**里 **166,846 行（85.0%）** 的品牌名会被替换成「无商品名」；`nc` 3,023 行、`eo` 2,292 行附带错。
   静态页（`name/*.html` 等 12 万页）由 Python 从库生成，**不受影响**——受影响的是站内**所有客户端渲染的搜索结果行**。
4. 最小改法：`site/build.py:11792-11793` 的元组补 `"t", "nc", "eo"` 三个字符串，**前端一行都不用改**
   （`decodeCore` 对普通列是通用赋值）。体积代价 **+1.18 MB raw / +22.4 KB gzip**。

---

## 1. 复现证据（改前 → 改后）

### 1.1 时序：为什么会「先正常、后翻转」

`site/build.py` 的客户端逻辑：

- 首搜走分片：`loadShardedIndex()` → `loadShards()`（`build.py:5891`），渲染出**正确**的品牌（`IDX` 只有当前 1–3 片，本例 1,591 行）。
- `ensureCoreInBackground()`（`build.py:5941`）在 `CORE_BG_DELAY = 9000` ms 安静期后、`requestIdleCallback` 空闲时拉 `core.json`（≈9.8 MB gzip）；
  到达后 `loadIndex()`（`build.py:5984`）把 `IDX` 整个换成解码后的 196,200 行并**静默重绘**（`if (quiet && box.value.trim()) render()`）。
- 于是用户在读第一屏时，结果**原地翻成「无商品名」**——正好是用户描述的观感。

补充：`coreNetAllowsPrefetch()`（`build.py:5933`）在 `saveData` / `slow-2g/2g/3g` 下**完全不预取 core**
→ 手机省流 / 弱网用户永远只看到分片，**看不到这个 bug**；桌面用户必现。这解释了「为什么不是所有人都反馈」。
另外用户一旦切国家下拉（`ensureIndexOnDemand()`，`build.py:5980`），core 立刻加载，翻转即刻发生。

### 1.2 实测 DOM（本机 8000 端口，`site/dist` 原样产物）

命令：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py serve.py 8000
# 浏览器打开 http://127.0.0.1:8000/?lang=zh&q=Tylenol ，先看首屏（分片），等 ~10 s 再看（core）
```

同一次页面会话内抓取（`#out [data-brand]` / `.brand-none` / `.match-name` / `.res-nobrand`）：

| 查询 | 阶段 | `IDX.length` | 品牌格 | 无商品名 | 命中名 | 「有 N 条记录没有商品名」提示 | 首行品牌列 |
|---|---|---:|---:|---:|---:|---|---|
| Tylenol | **分片** | 1,591 | 20 | 0 | 0 | 无 | `TYLENOL FILM COATED TABLETS 500MG` |
| Tylenol | **core** | 196,200 | 36 | **27** | **36** | **有 187 条记录没有商品名** | **无商品名** |
| Tylenol | 修后（模拟） | 196,200 | 36 | 1 | 10 | 无 | `TYLENOL FILM COATED TABLETS 500MG` |
| 泰诺 | core 改前 | 196,200 | 19 | 2 | 19 | 有 3 条 | 厂家： 上海强生制药有限公司 |
| 泰诺 | 改后 | 196,200 | 19 | 0 | 11 | 无 | `泰诺` |
| Lipitor | core 改前 | 196,200 | 19 | 16 | 19 | 有 3 条 | 无商品名 |
| Lipitor | 改后 | 196,200 | 19 | 4 | 7 | 无 | `Lipitor` |
| Paracetamol 500mg | core 改前 | 196,200 | 36 | 26 | 36 | **有 200 条** | 无商品名 |
| Paracetamol 500mg | 改后 | 196,200 | 36 | 14 | 24 | 有 30 条 | `Paracetamol 500mg tablets` |

「修后」= 在页面里把分片的 `t/nc/eo` 回填进 `IDX` 再 `render()`，**等价于「core.json 补三列」的效果**（不改 build.py、不改 dist）。

关键读数说明：

- `命中名` 计数 = 36/36，即**每一行**都进了 `brandHTML()` 的无商品名分支，与用户「原名退到命中名」完全一致。
- `.res-nobrand` 提示的数字是假的：Tylenol 实际 0 条、显示 187 条（=本次结果总行数）；Paracetamol 500mg 实际 30 条、显示 200 条。
  该数字来自 `build.py:5595` `shown.filter(x => x[2] && x[2].t !== 1).length`，`t` 缺失时所有行都算「无商品名」。
- 泰诺一行的首列显示「厂家： 上海强生制药有限公司」而不是「无商品名」，是 `build.py:4148` 的 CN 兜底（`cnMah`）先把 CN 行换成了厂家；
  改后该兜底从 17 行回落到 11 行（真·无商品名的 CN 行）。**所以「无商品名」计数会低估 CN 侧的错**。

### 1.3 数据层证据（只读，不写库不写 dist）

```
core.json cols  : atc c cu d db dp f g gn k l m ml mn mu n rl s sl u v vs wi x xz
shard 条目字段  : atc c cu d db eo f g gn k l m ml mn mu n nc q rl s sl t u v vs wi x xz
core 缺失字段   : ['eo', 'nc', 't']           ← 差值只有这 3 个，行数完全一致
core n          : 196,200 ；109 个分片行数合计 : 196,200 ；k 集合相等（无丢行、无改名）
```

同一条 `Tylenol` 在两种产物里的样子：

```
[shard]  k='tylenol'  d='TYLENOL FILM COATED TABLETS 500MG'  t=1  nc=0  eo=0  n=1  c=['SG']
         → brandHTML 走「正常显示商品名」
[core ]  k='tylenol'  d='TYLENOL FILM COATED TABLETS 500MG'  t=None  nc=None  eo=None  n=1  c=['SG']
         → brandHTML 走「无商品名 + 命中名: TYLENOL FILM COATED TABLETS 500MG」
```

复现脚本（只读 `site/dist`，可重跑）：

```powershell
& $py .tmp\probe_keys.py       # core cols vs shard 字段并集
& $py .tmp\repro_tylenol.py    # 用 JS decodeCore 同逻辑解码 core，逐字段对照 Tylenol
& $py .tmp\probe_t.py          # t/nc/eo 计数
& $py .tmp\size_delta2.py      # 补三列后的 raw / gzip 增量（按 k 精确对齐）
```

---

## 2. 根因：具体代码路径

### 2.1 缺失环节（唯一一处）

`site/build.py:11792-11793`，`encode_core()` 的字段白名单：

```python
    for f in ("c", "x", "xz", "atc", "s", "l", "f", "n", "v", "vs", "u", "cu", "mu", "ml", "g", "gn",
              "m", "mn", "db", "sl", "rl", "wi"):
```

- 这个元组是**手写**的，值全部走 `e.get(f)`（`build.py:11794`）→ **不在元组里的字段直接被丢掉**。
- 条目里其实有 3 个字段不在元组里，都在 `load_index()` 里生成：

| 字段 | 生成位置 | 含义 | 全量行数 |
|---|---|---|---:|
| `t` | `build.py:7644` `"t": 1 if a["trade"] else 0` | 1=是 trade 名；0=只有通用名 | `t==1` **166,846 / 196,200 = 85.0%** |
| `nc` | `build.py:7648` `"nc": 1 if not a["sids"] else 0` | 1=名称层（无成分记录） | 3,023 |
| `eo` | `build.py:7649` `"eo": 1 if a["export"] else 0` | 1=Export Only | 2,292 |

- 时间线（`git log -S` 可复核）：`encode_core()` 自 **v0.4.0**（`74fbab201`）就在；
  `t` 来自 **v0.9.0 task-19**（`989d9c38e`「大类 v2 + 矩阵 3 列 + 无商品名/厂家页」），
  `nc`/`eo` 来自 v0.9.1 task-28（`build.py:7647` 注释）。**编码器没跟着加列**——属于「新字段只加在写入侧、忘了读取侧」的典型漂移。
  v0.6.1 曾为 B7 CSV 导出单独补过 `f`（见 `build.py:11740-11741` 注释「f 加入核心…除 f 外 19 字段已验证 0 差异」）——
  那句「19 字段已验证」是在 `t/nc/eo` 出生**之前**做的快照，也是这个坑的第一次告警，说明靠人工核对字段早晚会漏。

### 2.2 为什么分片是对的、core 是错的

- 分片：`encode_shards()`（`build.py:11906-11952`）对 `entries` 逐条 `json.dumps(e)` → **原样**，字段天然齐全。
- core：`encode_core()`（`build.py:11773-11810`）按元组挑选列 → 缺 3 列。
- 两者在同一处 `main()` 里写：core 在 `build.py:12464-12467`，分片在 `12484-12489`。

### 2.3 前端：不需要改，但要知道它踩在哪

`decodeCore()`（`build.py:5749-5772`）对普通列是通用赋值：

```js
} else if(Array.isArray(col)){            // 普通列
  for(let i = 0; i < n; i++) out[i][f] = col[i];
}
```

→ **core 里只要有这一列，前端就自动拿到**。因此前端零改动。

真正被 `undefined` 打到的地方：

| 位置 | 代码 | 症状 |
|---|---|---|
| `build.py:4139` | `if(e && e.t !== 1){` | 走「无商品名」分支（**主症状**） |
| `build.py:4144-4146` | `matched` span | 原名退到「命中名: …」（**主症状**） |
| `build.py:4155-4156` | `.brand-none` | 显示「（无商品名）」 |
| `build.py:4168` | `if(e && e.nc){` | 名称层条目不再显示「成分未收录」，改成显示成分名 |
| `build.py:4365` / `4490` | `e.eo ? badge.export_only` | Export Only 徽标消失（2,292 行） |
| `build.py:5595-5598` | `shown.filter(x => x[2] && x[2].t !== 1)` | 「有 N 条记录没有商品名」数字 = 全部结果行 |

`brandHTML()` 的调用点只有三处，都在客户端结果渲染里：`build.py:4379`（宽表）、`4509`（紧凑表）、`5646`（同成分其他商品列表）。

---

## 3. 影响面

| 维度 | 数字 / 结论 |
|---|---|
| 索引条目总数 | 196,200（core 与 109 个分片合计一致，无丢行） |
| 会被错标成「无商品名」的条目 | **166,846（85.0%）** = `t==1` 的行 |
| `nc` 相关错标 | 3,023 行（名称层条目成分列变成假成分名） |
| `eo` 相关错标 | 2,292 行（Export Only 徽标消失） |
| 受影响页面 | **站内所有搜索结果视图**（`index.html` 的 `#out`，含 `?q=` 深链、`?country=` 国家视图、"同成分其他商品"/品牌家族区块） |
| 不受影响 | 12 万+ 静态页（`name/*.html`、`drug/*.html`、`combo/*.html`…）——由 Python 侧从 `load_index()` 条目/数据库生成，验证：`/name/lipitor.html` 返回 200、3,678 B、`无商品名` 出现 0 次 |
| 不受影响 | `lib/search.py` / `cli.py` / 三语测试——走 SQL 直查，`brand` 字段自算（`lib/search.py:89/389/657`），不读 core.json |
| 其它 core.json 消费方 | `render_dashboard.py:128`（只取文件大小）、`deploy/ci_checks.py:371`（只查体积）、`deploy/verify_live.py:260`（只查体积/编码）——都**不解析字段**，不受影响 |
| 触发条件 | 桌面端 ~9–17 s 后自动触发；`?legacy=1` 同样走 core（`build.py:5776-5781`），一样错；`saveData`/2G/3G 用户不加载 core，看不到 |
| `legacy-mini` 兜底 | `build.py:12470-12474` 的白名单 `{k,d,dp,c,x,s,l,n,v,u}` 也不含 `t` → 若开启 `WRITE_LEGACY_MINI=1`，兜底路径**同样**显示无商品名（默认关闭，当前 dist 无此文件） |

---

## 4. 最小改法

### 4.1 当天热修（1 处、3 个字符串、前端零改动）

`site/build.py:11792-11793`：

```diff
     for f in ("c", "x", "xz", "atc", "s", "l", "f", "n", "v", "vs", "u", "cu", "mu", "ml", "g", "gn",
-              "m", "mn", "db", "sl", "rl", "wi"):
+              "m", "mn", "db", "sl", "rl", "wi", "t", "nc", "eo"):
```

说明：

- 三个字段都是 0/1 整数，走 `else` 分支（`build.py:11807-11808`）存成普通列 `[1,0,1,…]`；
  `decodeCore` 的 `Array.isArray(col)` 分支直接赋值 → `e.t` 恢复为 0/1，`e.t !== 1` 判定恢复正常。
- **不要**把它们加进 `CORE_DICT_COLS`（`11742-11743`）：实测两种写法体积完全相同（+1.18 MB raw），普通列更简单。
- 不需要动 `CORE_ARRAY_COLS`（这三个不是数组）。

体积实测（按 `k` 精确对齐重建，只读测量，未写 dist）：

| 产物 | raw | gzip -9 |
|---|---:|---:|
| 现状 `core.json` | 41.62 MB | 9.773 MB |
| 补 `t/nc/eo` 后 | 42.80 MB（**+1.18 MB**） | 9.796 MB（**+22.4 KB，+0.23%**） |

仍在 `deploy/publish.ps1` 护栏内（raw 11–50 MB / gzip 2.5–12 MB）。

### 4.2 防复发（建议与 4.1 同批，避免第三次踩）

根因不是「少 3 个字段」，而是「字段清单靠手写、没有断言」。两个补丁：

**(a) 把字段清单提成常量 + 构建期断言**（`site/build.py`，`encode_core()` 之前）：

```python
# core 必须逐行携带的列：新增 load_index() 字段时必须同步这里（否则 core 缺列 → 客户端渲染错位）
CORE_FIELDS = ("c", "x", "xz", "atc", "s", "l", "f", "n", "t", "v", "vs", "nc", "eo",
               "u", "cu", "mu", "ml", "g", "gn", "m", "mn", "db", "sl", "rl", "wi")


def encode_core(entries) -> dict:
    """entries（load_index 的结果）→ 列式 + 字典编码的 core 对象。"""
    # P0-1 守卫：core 一旦漏列，decodeCore 后该字段是 undefined，前端静默渲染错位
    # （v0.9.0 的 t 就是这样丢了 85% 的商品名）。宁可构建失败，不要发布缺列的 core。
    missing = {f for e in entries for f in e} - set(CORE_FIELDS) - {"k", "d", "q"}
    if missing:
        raise SystemExit(f"encode_core 漏字段 {sorted(missing)}：core.json 会缺列，客户端渲染错位")
    ...
    for f in CORE_FIELDS:
        ...
```

**(b) 产物级守卫**（建议接进 `deploy/ci_checks.py` 的 `check_dist()`，约 15 行，只读 dist）：

```python
def check_index_fields(dist: Path) -> None:
    """core.json 的列必须覆盖分片条目的全部字段（P0-1：t/nc/eo 曾整体缺失）。"""
    idx = dist / "data" / "idx"
    core = json.loads((idx / "core.json").read_bytes().decode("utf-8"))
    man = json.loads((idx / "manifest.json").read_bytes().decode("utf-8"))
    core_cols = set(core["cols"]) - {"dp"}          # dp 是 d 的大小写补丁列，core 独有
    shard_cols: set[str] = set()
    for files in man["buckets"].values():
        for f in files:
            arr = json.loads((idx / Path(f["f"]).name).read_bytes().decode("utf-8"))
            for e in arr:
                shard_cols.update(e)
    missing = shard_cols - core_cols - {"q"}         # q 在 core 里是稀疏下标数组
    if missing:
        problems.append(f"core.json 缺列 {sorted(missing)}（分片有、core 没有）")
```

（`problems` 是 `check_dist` 里已有的列表，直接 append 即可。）

### 4.3 可选、低优先

- `WRITE_LEGACY_MINI=1` 的兜底子集（`build.py:12470-12471`）建议加 `"t"`（+≈0.4 MB raw，gzip 后几十 KB），
  否则「core 损坏 → 兜底」这条路上仍然全是「无商品名」。`nc/eo` 在兜底路径可以接受降级，但要写注释说明。
- `build.py:11723` 的注释「decodeCore 解码回与 index.json 完全同构（同字段、同顺序）」这句当初就是错的**承诺**，
  建议改成「同字段（字段清单见 CORE_FIELDS），顺序无关」。

---

## 5. 改前 / 改后预期对照

同一次查询、同一台机器、同一份 dist，只差 core 有没有 `t/nc/eo`：

| 观察点 | 改前（core 加载后） | 改后 |
|---|---|---|
| Tylenol 首行品牌列 | `无商品名` | `TYLENOL FILM COATED TABLETS 500MG` |
| Tylenol 命中名 span | 36 个（每行都有） | 10 个（只剩真·名称层行） |
| Tylenol `.brand-none` | 27 | 1 |
| Tylenol 无商品名提示 | 「有 **187** 条记录没有商品名」 | 不出现（实际 0 条） |
| Lipitor `.brand-none` | 16 | 4 |
| Paracetamol 500mg 提示 | 「有 **200** 条」 | 「有 **30** 条」（真实数量） |
| 泰诺 首列 | `厂家： 上海强生制药有限公司` ×17 | `泰诺` / `泰诺林` …（厂家兜底降到 11 行） |
| Export Only 徽标 | 不显示 | 2,292 行恢复 |
| 名称层「成分未收录」徽标 | 不显示，改印成分名 | 3,023 行恢复 |
| 分片阶段（前 ~9 s） | 正常 | 正常（不变） |
| core.json | 41.62 MB raw / 9.773 MB gz | 42.80 MB raw / 9.796 MB gz |

---

## 6. 回归用例清单（发布前必跑）

在 `site/dist` 全新构建后，按这个顺序验；每条都要看 **core 加载前** 与 **core 加载后** 两个状态（间隔 ~10 s 或切一次国家下拉强制加载）。

| # | 查询 | 断言 |
|---|---|---|
| 1 | `Tylenol` | 两阶段首行都是 `TYLENOL FILM COATED TABLETS 500MG`；`.brand-none` 两阶段都 ≤1；无 `res-nobrand` 提示；`命中名` 数两阶段一致（≈10） |
| 2 | `泰诺` | 首列是 `泰诺` 不是「厂家：…」；`.brand-none` = 0；`命中名` ≈11 |
| 3 | `Lipitor` | 首列 `Lipitor`；`.brand-none` = 4（真·名称层）；`命中名` = 7 |
| 4 | `Paracetamol 500mg` | `res-nobrand` 文案必须是「有 **30** 条记录没有商品名」（改前是 200）；首行 `Paracetamol 500mg tablets` |
| 5 | 任一带 Export Only 的产品（`eo==1`，2,292 行里取一条） | `.badge.export` 在 core 加载后仍存在 |
| 6 | 名称层条目（`nc==1`，3,023 行里取一条，如某无成分收录的名字） | 成分列显示「成分未收录」，不是把名字当成分 |
| 7 | `?country=US`（切国家触发 `ensureIndexOnDemand`） | 切换后品牌列不翻转 |
| 8 | 结构守卫 | 构建日志/`ci_checks` 无「core.json 缺列」；`core.json` 的 `cols` 含 `t`/`nc`/`eo` |

可直接复用的机器判据（只读 dist，构建后跑）：

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\probe_keys.py     # 期望输出：core 缺失字段: []（改前是 ['eo','nc','t']）
& $py .tmp\probe_t.py        # 期望 t==1 仍为 166,846 行（数值不应变，只是变得可读）
```

人工三语抽查（`AGENTS.md` §5 要求）：zh `泰诺` / en `Tylenol` / es `Paracetamol 500mg`，各看「分片 → core」两帧。

---

## 7. 边界与没做的事

- **没有改任何代码**：`site/build.py` 当前由 site-ui 单写窗口占用；本报告只给补丁片段，落地由 site-ui / Lead 排。
- **没有重建站**：`site/dist` 是 v0.11.1（2026-11-10 13:51）产物，未写入、未删除；验证用的是它的只读副本 + 本机 8000 端口预览。
- **没有写库**：全程只读 `site/dist/data/idx/*.json`；`db/q.py`、`lib/search.py` 均未执行写路径，`data/drugs.db` 未被打开写入。
- **体积数字是「按 k 对齐重建 core 后实测」，不是真构建产物**：值分布与顺序都来自现有分片，gzip 比值可信（0/1 列压缩率极高），
  误差应在 ±1 KB gz 级别；正式发布仍须以 `site/build.py` 实跑出的 `core.json` 大小为准，并同步 `publish.ps1` 护栏与 `CHANGELOG`。
- **首屏守卫未跑**：本次不改站点行为（只补数据列，首屏体积 +22 KB gz），按 §5 仍需在真正落地补丁后跑一次
  `deploy/first_screen_check.py`，改前 / 改后各一次。
- **未覆盖**：`brandHTML()` 在 `t=1` 但 `u`（名字页 URL）为空时渲染成不可点文本（如本例 SG-only 的 Tylenol）——
  这是既有设计（v0.5.3 规则），不是本次 P0-1 范围；但它会让「Tylenol 首行不可点」，用户走查时的 P4「Tylenol 摘要要说明概括的是哪条候选」可一并看。
- **顺带发现（非本任务，供 Lead 派单）**：`docs/下一轮优先级-20261111.md` P0-1 把根因写成「分片索引与完整索引的字段映射不一致」，
  实测应更正为「core 列式编码漏了 `t`/`nc`/`eo` 三列」；建议把本条结论回写进该文档，避免下轮按错误方向排查。

---

## 附：关键文件:行索引

| 位置 | 作用 |
|---|---|
| `site/build.py:7644` / `7648` / `7649` | `t` / `nc` / `eo` 在 `load_index()` 里生成 |
| `site/build.py:11742-11744` | `CORE_DICT_COLS` / `CORE_ARRAY_COLS` 编码方式白名单 |
| **`site/build.py:11792-11793`** | **`encode_core()` 手写字段清单（根因所在）** |
| `site/build.py:11807-11808` | 普通列分支：`cols[f] = vals` |
| `site/build.py:11906-11952` | `encode_shards()`：分片原样序列化（字段齐全） |
| `site/build.py:12464-12467` / `12484-12489` | core / manifest+分片写盘 |
| `site/build.py:12470-12474` | `legacy-mini` 子集白名单（同样缺 `t`） |
| `site/build.py:5749-5772` | `decodeCore()`：普通列通用赋值 → 前端无需改 |
| `site/build.py:5941-5978` | `ensureCoreInBackground()`：`CORE_BG_DELAY=9000` ms 后拉 core |
| `site/build.py:5984-6018` | `loadIndex()`：core 到位后静默重渲染 |
| `site/build.py:4136-4165` | `brandHTML()`：`e.t !== 1` 判定（主症状） |
| `site/build.py:4168` | `ingredientHTML()`：`e.nc` 判定 |
| `site/build.py:4365` / `4490` | Export Only 徽标 `e.eo` |
| `site/build.py:5595-5598` | 「有 N 条记录没有商品名」计数 |
| `deploy/ci_checks.py:356-394` | `check_dist()`：目前只查 core 体积，**没有字段一致性检查** |
