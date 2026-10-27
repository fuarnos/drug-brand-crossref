# 索引 P1 实现报告：列式 + 字典编码核心（34.8 MB → 15.3 MB raw / 3.84 MB 线上预估）

> 任务：task-7（索引 P1：列式 + 字典编码）。依据：`reports/index-perf-plan.md` §0 / §2 / §5。
> 实现：`site/build.py`（唯一改动的代码文件）内新增编码器 + `APP_JS` 解码器；`data/idx/core.json` 为主索引，`data/index.json` 双写保留作回退。
> 行为等价性：构建产物 `assets/app.js` 与现有 v0.3.5 `site/dist/assets/app.js` 在真实数据上逐查询对拍（21 查询 + 3 国家视图 + 清空），`out.innerHTML`/`meta`/ARTG 区域**逐字节一致**；全量 126,915 条 × 14 字段 + `q` 解码结果**零差异**。
> 本任务未跑 git、未发布、未改 `site/dist` / `data/drugs.db` / 其他跟踪文件；构建全部写 `.tmp/dist-p1/`（SITE_OUT）。

---

## 0. 结论（TL;DR）

| 指标 | v0.3.5（现状） | P1（本次） | 变化 |
|---|---:|---:|---:|
| 检索数据 raw | 34,795,714 B（34.8 MB） | **15,288,147 B（15.3 MB）** | **-56.1%** |
| 检索数据 gzip -9 | 5,823,291 B | **3,693,064 B** | **-36.6%** |
| 首搜传输（gzip 实测；线上≈×1.041） | 6,062,430 B（线上实测） | **≈3,844,480 B（预估）** | **-36.6%** |
| 首搜总要下载（core+aliases+confused） | 5,841,894 B gzip / ≈6.08 MB 线上 | **3,711,667 B gzip / ≈3.86 MB 线上** | 省 2,130,227 B gzip（**-36.5%**） |
| 首屏（未输入，html+js+css gzip） | 17,032 B（P0） | **18,002 B** | +970 B（解码器代码约 +1 KB） |
| 首屏页面加载请求数 | 0（P0 懒加载） | **0（保持）** | 不变 |
| 解码耗时（126,915 条→IDX） | `JSON.parse` 207 ms / 堆 83.9 MB | parse 42 ms + `decodeCore` **159 ms** / 堆 **58.1 MB** | 耗时基本持平，堆 **-30.7%** |
| 功能等价 | — | 全量数据零差异 + 真实 render 逐字节一致 | **通过** |

- **净收益是传输字节**：首搜 6.06 MB → 3.84 MB（线上预估），raw 体积 -56%；解析/解码耗时没有明显下降（V8 解析 34.8 MB JSON 本来就快），这部分留给 P2 分片解决。
- **IDX 顺序刻意保持原样**（不按 `k` 排序）：`render()` 的全并列排序、国家视图 `inCountry`、同成分 `same.ing` 都直接依赖 `IDX` 顺序；按 `k` 排序虽能再省 ~0.34 MB gzip，但会改变结果行顺序。改用「`d` 与 `k` 的大小写冗余」来补回体积（见 §1），最终**比计划里的 V3b 3.93 MB 还小**。
- 失败/回滚三层都在：`?legacy=1` 走旧 `index.json`（core 零请求）、core 请求失败/解码抛错自动回退 `index.json`、`index.json` 继续双写（发布体积 +15.3 MB raw，可接受）。
- 发布只需正常 build + publish：**多 1 个文件**（`data/idx/core.json`），`deploy/publish.ps1` 与 `deploy/pages.yml` 均无需改动（已核对 robocopy 全量拷贝、`index.json ≥5 MB` 检查仍通过）。

---

## 1. 编码格式（`data/idx/core.json`，格式版本 v1）

单个 JSON 文件（`separators=(",",":")`，非 ASCII 原样输出）：

```jsonc
{
  "v": 1,                     // 格式版本（解码端校验结构，坏结构抛错→前端回退 index.json）
  "n": 126915,                // 条数
  "cols": {
    "k":  ["...", ...],       // 检索键，原样、原顺序（保持 IDX 顺序 = 保证 render 行为不变）
    "d":  ["...", ...],       // 展示名；可由 k + dp 还原时存 ""
    "dp": ["0-2,5", ...],     // 大小写位置模式：把这些位 toUpperCase 即得 d（无则 ""）
    "c":  {"d": [["US"],...], "i": [3,3,0,...]},   // 字典列：字典值 + 每行下标
    "x":  {"d": ["...", ...], "i": [...]},         // 成分展示串字典（20,787 种）
    "s":  {"d": [["1 mg"],...], "i": [...]},       // 剂量数组字典（23,679 种）
    "l":  {"d": ["info","warning","severe"], "i": [...]},
    "v":  {"d": ["...", ...], "i": [...]},         // 主成分 id（含 CN 字符串 id，10,448 种）
    "vs": {"d": [null, ["a","b"], ...], "i": [...]}, // 多成分 id 列表字典（9,383 种）
    "u":  ["name/xxx.html", "", ...],              // 普通列：名字页文件名
    "g":  {"d": [...], "i": [...]},                // 品牌族标签（5 种）
    "gn": {"d": [...], "i": [...]},                // 品牌族说明（5 种）
    "m":  {"d": [...], "i": [...]},                // MAH 字典（13,554 种）
    "n":  [12, 3, ...],       // 普通列：包装数
    "mn": [5, 2, ...]         // 普通列：MAH 数量
  },
  "q": [12, 345, ...]         // q=1 的稀疏行下标（163 条，加拿大数字/符号开头残名降权）
}
```

### 1.1 字段取舍

| 字段 | 编码 | 理由 |
|---|---|---|
| `k` | 原样字符串列，**保持 entries 原顺序** | 匹配主键；排序会改变 render 输出（见下） |
| `d` | `d==k` → `""`（解码得 k）；`d` 与 `k` 只差 ASCII 大小写 → `""` + `dp` 位置模式；否则存原文 | `d` 与 `k` 高度冗余（74,609/126,915 条只是大小写不同），显式 delta 比让 gzip 猜更省：这一项就省 **343,581 B gzip** |
| `dp` | `'0'` / `'0-2,5'` 等闭区间位置模式 | 构建时逐字符验证「toUpperCase 后 == d」，只接受 ASCII 大小写；`ß`/`İ` 等非 ASCII 映射一律存完整 `d`，保证浏览器 JS 与 Python 行为一致 |
| `c` `x` `s` `l` `vs` `g` `gn` `m` | 字典列 `{d,i}` | 重复率高的字段（`l` 3 种、`c` 70 种、`x` 20,787 种…）；`c/s/vs` 先 JSON 化成字符串再进字典，解码时直接给共享数组引用（render 只读，安全），不需要逐行 `JSON.parse` |
| `v` `n` `mn` `u` | 普通列 | `v` 虽是小整数但含 CN 字符串 id（如 `cn-ef1fa3539d`），实测字典列 260 KB gz vs 原样列 399 KB gz，仍走字典；`n/mn` 原样 int 列最小；`u` 稀疏化实测反而更大（168 KB vs 134 KB gz），保持原样 |
| `q` | 稀疏下标数组 | 只有 163 条，原样存 163 个字符串太浪费 |
| `f` | **丢弃** | `app.js` 中 0 处引用。若保留成字典列实测 +295,814 raw / +56,917 gzip；客户端 render/国家视图/同成分/品牌族/ARTG 全都不用 `f`，全量对拍已证明丢弃后输出逐字节一致 |

### 1.2 为什么不做 `k` 排序（与计划 V3b 的差异）

`site/dist/data/index.json` 的条目顺序是 `n`（包装数）降序，`render()` 里：

1. `hits.sort(...)` 的并列兜底是**稳定排序**，完全并列时保留 `IDX` 原顺序；
2. 国家视图 `inCountry = IDX.filter(...)`、同成分 `same.ing` 的 `others = IDX.filter(...)` 的行顺序就是 `IDX` 顺序，且 `slice(0,40)` 取前 40 条。

因此按 `k` 排序会改变这些区块的可见顺序。实测（`.tmp/dist-p1/_verify/measure_encoding.py`，真实 126,915 条数据，本机 gzip -9）：

| 编码变体 | raw | gzip -9 | 说明 |
|---|---:|---:|---|
| A. V3 原顺序（计划 §3.2 口径） | 16,175,360 | 4,163,323 | 基线 |
| B. V3b 按 `k` 排序 | 16,031,757 | 3,774,740 | 会改变 IDX 顺序 |
| B2. 按 `k` 排序 + d delta（无排列） | 15,144,544 | 3,435,860 | 仍是「改变顺序」的方案，不可用 |
| C. B2 + 顺序还原排列 `o` | 15,921,845 | 3,780,870 | 排列列 gzip ≈ 337 KB，基本吃掉排序收益 |
| **D. 原顺序 + d 大小写 delta（本次）** | **15,288,147** | **3,693,064** | 顺序 100% 保留，且比 C（还原顺序）还小 88 KB |

> A/B 与计划 §3.2 的 V3/V3b 数字（16,175,813 / 16,031,541 raw，4,163,466 / 3,774,727 gzip）差 ~0.01%：数据已从 v0.3.3（34,795,787 B）更新到 v0.3.5（34,795,714 B），且 A/B 用同一复刻脚本重算。

结论：排序收益（≈389 KB）与还原顺序的排列代价（≈337 KB）接近抵消，而「按 k 排序且不还原」会改变 render 输出（不可用）；
`d/k` 的大小写冗余（≈344 KB）不依赖排序即可拿到，还顺带丢掉 `f`。最终选「原顺序 + d delta + 删 f」，**行为零变化**且比任何保序排序方案都小。

---

## 2. 改动点（只改了 `site/build.py`）

| 位置（当前行号） | 改动 |
|---|---|
| L13–15 | 模块文档串新增 `data/idx/core.json` 产物说明 |
| L742–800 | `APP_JS` 新增 P1 解码段：`applyCase()`、`decodeCore()`、`fetchJSON()`、`loadMainIndex()`；`loadIndex()` 改为拉 `loadMainIndex()` + aliases + confused（失败重试/提示逻辑不变） |
| L1910–2005 | 新增编码器：`CORE_DICT_COLS` / `CORE_ARRAY_COLS` 常量、`_d_case_pattern()`、`encode_core()` |
| L2041 | 版本注入：`data/idx/core.json` → `data/idx/core.json?v=BUILD_V`（`data/index.json` 原有处理保留；两个 URL 各自带版本号） |
| L2072–2078 | `main()` 在写完 `index.json` 后，同一份 `entries` 再写 `data/idx/core.json`，并打印两份体积；目录 `data/idx/` 自动创建 |

### 2.1 前端加载链（保持 P0 懒加载与全部触发时机）

```
页面加载          → 0 fetch（首屏仍不加载索引，P0 行为不变）
首次 input/focus/示例/?q= → loadIndex()
   ├─ ?legacy=1          → data/index.json（旧路径，不碰 core；回滚开关）
   └─ 默认               → data/idx/core.json → JSON.parse → decodeCore() → IDX
        └─ 请求失败 / 非 200 / 解码抛错 → console.warn + 自动回退 data/index.json
aliases.json / confused.json 与索引并行拉（同上）
```
- `decodeCore()` 先做结构校验（`cols.k` 必须是数组、`n` 必须是 number），坏结构抛错→走回退；F2 测试已覆盖。
- `?legacy=1` 的页面加载行为、加载提示、失败重试按钮、focus 预取、`?q=` 深链全部沿用 P0 代码，只在取数据处分支。
- 同步修正：`loadIndex()` 的失败提示文案/重试逻辑未变；提示文案仍写「约 6 MB」（实际首搜约 3.86 MB，保守值，未改 HTML 提示，见 §6 注意事项）。

---

## 3. 构建与验证证据

### 3.1 构建（SITE_OUT 到 `.tmp/dist-p1`，未覆盖 `site/dist`）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:SITE_OUT='D:\同种药物商品名剂量对应网站\.tmp\dist-p1'
& $py -X utf8 site/build.py
```

构建日志（退出码 0）：

```
building index ...
  126915 keys
  core.json  15.3 MB (index.json 34.8 MB)
building nickname index ... 422 nicknames
building confused index ... 44 directions
building ARTG name index ... 34594 ARTG names
...
== done ==
  drug pages : 12864   name pages : 17868   confused : 22 pairs
  index.json : 34.8 MB  total size : 149.5 MB
```

- `node --check .tmp/dist-p1/assets/app.js` → **通过（exit 0）**。
- 构建产物 `data/index.json`、`aliases.json`、`confused.json`、`artg.json` 与现有 `site/dist` **逐字节相同**（SHA256 `B44A5700…` 等），因此对拍基线完全一致。
- 编码器在 126,915 条真实数据上耗时约 1.6 s（构建内一次，可忽略）。

### 3.2 全量解码等价（`_verify/decode_full.mjs`）

用构建产物 `assets/app.js` **里真实的 `decodeCore`** 解 `data/idx/core.json`，与同一构建的 `data/index.json` 逐条逐字段比较：

```
core.json 163 q-flags; decoded 126915 entries in 150 ms
PASS  全量解码等价：126915 条 × 14 字段 + q，顺序一致（f 按设计丢弃）
```

- 覆盖 `k,d,c,x,s,l,n,v,vs,u,g,gn,m,mn` + `q` 稀疏标记 + **数组顺序**；mismatch = 0。
- 其中 `d` 的还原含 74,609 条（13,937 条 `d==k` + 60,672 条大小写模式重建），全部逐字符一致。

### 3.3 行为测试（`_verify/p1.test.mjs`，Node DOM 桩 + 真实 126,915 条数据，12/12 通过）

```
PASS  A. 静态：core 请求带 ?v= 且在 loadMainIndex() 内；index.json 只作 legacy/fallback；无 preload
PASS  A2. 首屏零 fetch、中英提示可见、input 可用（首屏仍不加载索引）
PASS  B. focus 预取 core（含 aliases/confused），未输入不渲染
PASS  C. 首次 input 加载 core → decodeCore → render（126,915 条，无 index.json 请求）
PASS  D. ?q= 深链立即加载 core 并渲染
PASS  E. ?legacy=1 一键回滚为旧 index.json 路径（core 零请求）
PASS  F. core 网络失败 → 自动回退 data/index.json，结果正常
PASS  F2. core 结构损坏（decodeCore 抛错）→ 自动回退 index.json，结果正常
PASS  S. 新构建 data/index.json、aliases、confused、artg 与 site/dist 逐字节相同（对拍基线一致）
PASS  G. 旧/新 app.js 逐字节一致（21 查询 + 3 国家视图 + 清空）
PASS  H. core 失败自动回退路径与旧 app.js 逐字节一致（6 查询 + 2 国家视图）
PASS  I. ?legacy=1 路径与旧 app.js 逐字节一致（3 查询，core 零请求）
== ALL 12 CHECKS PASSED ==
```

**G 项对拍**：`site/dist/assets/app.js`（v0.3.5，读 `index.json`）vs `.tmp/dist-p1/assets/app.js`（读 `core.json`+解码），
同一套 DOM 桩、同一份数据，逐查询比较 `out.innerHTML`、`meta.textContent`、ARTG 区域，**逐字节相同**：

- 查询（21 个）：`Lipitor 20mg`、`Lipitor`、`泰诺`、`两只青蛙`、`利嗪`、`acetazolamide`、`aspirin`、`Gaviscon`、`Benadryl`、`Metformin 500mg`、`盐酸西替利嗪片`、`Lipit0r`、`zzzznotadrug`、`123diet`、`arthrostrong`、`arimizole`、`amoxicillin`、`ibuprofen`、`atorvastatin`、`co codamol`、`Zepbound`；
- 国家视图（3 个）：`Lipitor`/`Gaviscon`/`泰诺` 选 US（含 `tag us` 断言）；
- 清空输入（out 清空一致）；
- 覆盖功能路径：exact / fuzzy / nickname / confused / same-ingredient / brand-family / ARTG 兜底 / CJK contains / SEV+WARN 碰撞徽标 / country，全部命中。
- 对拍样本输出规模：如 `Gaviscon` 66,454 B、`aspirin` 58,808 B、`两只青蛙` 32,689 B、`Lipitor 20mg` 30,572 B。

**H/I 项**：核心失败自动回退路径、`?legacy=1` 路径分别与旧 app.js 逐字节一致（回退后功能完全等价）。

### 3.4 构建产物对拍（`_verify/site_diff.py`，vs 现有 `site/dist`）

```
旧构建文件 30,749  新构建文件 30,757（其中 7 个是 .tmp 验证脚本）  逐字节相同 10
新增文件: ['data/idx/core.json', '_verify/*']    仅在旧构建: []
差异分类: {"only-version": 30497, "other": 1, "name-page-spec-order": 241}
  差异 [other] assets/app.js  new=21410 old=18995
  data/ 四个数据文件逐字节一致: {index.json: True, aliases.json: True, confused.json: True, artg.json: True}
体积: 旧 134.2 MB → 新 149.5 MB
```

- 除 `assets/app.js`（本次改动）外，全部 HTML 只差 `?v=BUILD_V`（每次构建必变）；
  241 个 name 页是**既有** PYTHONHASHSEED 排序抖动（文件字节数完全相同，P0 报告 §3.4 已记录，非本次改动）。
- **没有其他跟踪文件/其他页面内容变化**；新构建相对现有 dist 只多 `data/idx/core.json` 一个文件。

### 3.5 HTTP 冒烟（`python -m http.server` 临时端口 8792，用后即停）

```
PASS  index.html HTTP 200，含懒加载提示 / app.js?v= / 无索引 preload
PASS  /es/index.html HTTP 200，含懒加载提示
PASS  /zh/index.html HTTP 200，含懒加载提示
PASS  assets/app.js HTTP 200，含 core 请求 / index 回退 / ?legacy=1 / decodeCore
PASS  data/idx/core.json HTTP 200 — 15,288,147 B raw, n=126915, v=1
PASS  data/index.json（兼容回退）HTTP 200 — 34,219,360 chars
PASS  未知路径 404
== HTTP: 7/7 checks passed ==
```

### 3.6 解析/内存基准（`_verify/bench.mjs`，Node v24，本机）

| 路径 | 文件体积 | 耗时 | 新增 JS 堆 |
|---|---:|---:|---:|
| `index.json` → `JSON.parse` | 34.2 MB | 207 ms | 83.9 MB |
| `core.json` → `JSON.parse` + `decodeCore` | 15.0 MB | 201 ms（parse 42 + decode 159） | **58.1 MB（-30.7%）** |

- 传输/解析体积比 **44.0%**；耗时基本持平（V8 解析大 JSON 很快，主要成本是建 126,915 个对象）。
- 也就是说 P1 的收益在**网络字节**，不在首搜 CPU；CPU/交互延迟由 P2 分片解决。

---

## 4. 体积对比表

### 4.1 检索数据文件

| 文件 | raw | gzip -9 | 线上预估（×1.041） | 相对现状 |
|---|---:|---:|---:|---:|
| 现状 `data/index.json` | 34,795,714 | 5,823,291 | 6,062,046（线上实测 6,062,430） | — |
| **P1 `data/idx/core.json`** | **15,288,147** | **3,693,064（-36.6%）** | **3,844,480** | **raw -56.1% / gzip -36.6%** |
| `data/index.json`（双写保留） | 34,795,714 | 5,823,291 | 6,062,046 | 不变（仅回退/legacy 时下载） |

### 4.2 首搜下载（首次输入触发的全部请求）

| 组成 | 现状 gzip | P1 gzip | 说明 |
|---|---:|---:|---|
| 核心索引 | 5,823,291 | 3,693,064 | `index.json` → `core.json` |
| aliases | 17,722 | 17,722 | 未改动 |
| confused | 881 | 881 | 未改动 |
| **合计** | **5,841,894** | **3,711,667（-36.5%，省 2,130,227 B）** | 线上预估 6.08 MB → **3.86 MB** |

### 4.3 首屏（未输入时；仍不加载索引）

| 资源 | raw | gzip -9 | 线上预估 |
|---|---:|---:|---:|
| index.html | 3,968 | 1,652 | 1,720 |
| assets/app.js | 21,410（旧 18,995，+2,415） | 8,807（旧 7,835，+972） | 9,168 |
| assets/i18n.js | 16,133 | 6,076 | 6,325 |
| assets/style.css | 4,513 | 1,467 | 1,527 |
| **合计** | **46,024** | **18,002** | **18,740** |

首屏因解码器代码 +970 B gzip（17,032 → 18,002 B），仍约为旧「页面加载即拉索引」6.08 MB 的 **0.3%**。

---

## 5. 回滚方法

| 层次 | 操作 | 生效范围 / 已测 |
|---|---|---|
| ① 免发布（最快） | URL 加 `?legacy=1`（如 `…/?legacy=1`） | 立即改走旧 `data/index.json`，**core 零请求**（测试 E/I） |
| ② 自动兜底 | 无需操作 | `core.json` 404/网络失败/JSON 损坏/结构校验失败 → 前端自动回退 `index.json` 并 `console.warn`（测试 F/F2） |
| ③ 发布回滚 | gh-pages revert 到上一发布（由 Lead 执行） | 旧 app.js 仍读 `index.json`，且本次 `data/index.json` 字节未变，回滚后行为与 v0.3.5 完全一致 |
| ④ 源码回滚 | `git checkout -- site/build.py` 后重新构建/发布（Lead 执行；本子智能体未跑 git） | 回到 v0.3.5（P0）行为 |
| ⑤（可选）删回退文件 | 稳定一个版本后再删 `data/index.json`，需同步改 `publish.ps1` 的 ≥5 MB 检查、`app.js` 的 legacy/fallback 分支 | **本次不做**，跨文件改动另立任务 |

> 建议至少保留 `data/index.json` 一个发布周期；它也是「核心文件发布缺失/灰度不一致」时的唯一兜底。

---

## 6. 发布注意

1. **文件数 / 体积**：`site/dist` 30,749 → **30,750** 文件（+`data/idx/core.json`），dist raw 134.2 → **149.5 MB**（+15.3 MB），gz 增量约 +3.69 MB/次发布。GitHub Pages 1 GB 站点上限、文件数均宽裕。
2. **发布脚本无需改**：`deploy/publish.ps1` 用 `Get-ChildItem -Recurse` + `robocopy /E` 全量拷贝，`data/idx/core.json` 自动包含；其完整性检查（`index.html`、`data/index.json` ≥5 MB、文件数 ≥24,000、无 0 字节）全部仍通过。`deploy/pages.yml` 上传 `site/dist` 整个目录，也无需改。
3. **缓存破坏**：构建把 `data/idx/core.json` 与 `data/index.json` 都替换成带 `?v=<构建时间戳>` 的 URL，每次发版重新下载；旧缓存里的旧 `app.js` 仍会用旧 `index.json` URL，互不影响。
4. **首次发布后必须线上确认 gzip**（Pages 动态压缩，`data/*.json` 与 `index.json` 同类）：
   ```powershell
   curl.exe -sI -H 'Accept-Encoding: gzip, deflate, br' https://fuarnos.github.io/drug-brand-crossref/data/idx/core.json
   # 期望：HTTP 200 + content-encoding: gzip，Content-Length ≈ 3.7–3.9 MB
   ```
   若意外未 gzip（不应发生，`index.json` 实测已 gzip），临时用 `?legacy=1` 回滚并排查，勿长时间让用户下 15.3 MB 明文。
5. **提示文案**：首页静态提示仍写「约 6 MB（gzip）」（`build_index_page` 与 `APP_JS` 的 `HINT_IDLE`），比实际 3.86 MB 保守；本次未改文案以把改动面压到最小，可在下一版一起改成「约 4 MB」。
6. **真实浏览器验收**：本次用 Node DOM 桩 + 本地 HTTP 冒烟（同 P0 方法）验证，未在真机浏览器点击。发布前建议桌面/手机各点一次：首次输入、focus 预取、`?q=` 深链、`?legacy=1`、断网/404 回退、国家选择。
7. **`_verify/` 目录只存在于本任务 `.tmp/dist-p1`**（SITE_OUT 构建），不会进 `site/dist`/发布产物；重新构建会被清空，复现脚本见 §7。

---

## 7. 复现命令 / 交付物

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$node = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$env:SITE_OUT='D:\同种药物商品名剂量对应网站\.tmp\dist-p1'
& $py -X utf8 site/build.py
& $node --check .tmp\dist-p1\assets\app.js
& $node --max-old-space-size=4096 .tmp\dist-p1\_verify\decode_full.mjs
& $node --max-old-space-size=4096 .tmp\dist-p1\_verify\p1.test.mjs
& $py -X utf8 .tmp\dist-p1\_verify\sizes.py
& $py -X utf8 .tmp\dist-p1\_verify\site_diff.py
& $node --expose-gc --max-old-space-size=4096 .tmp\dist-p1\_verify\bench.mjs
# HTTP 冒烟（临时端口，用后即停）：
& $py -X utf8 -m http.server 8792 --bind 127.0.0.1 --directory .tmp\dist-p1
& $node .tmp\dist-p1\_verify\http_check.mjs http://127.0.0.1:8792/
```

| 交付物 | 内容 |
|---|---|
| `site/build.py` | 唯一代码改动：编码器 + `APP_JS` 解码器 + core 写出/版本注入（见 §2） |
| `.tmp/dist-p1/` | SITE_OUT 构建产物（30,757 文件，含新 `data/idx/core.json`） |
| `.tmp/dist-p1/_verify/{decode_full.mjs,p1.test.mjs,http_check.mjs,bench.mjs,sizes.py,site_diff.py,measure_encoding.py}` | 可复跑验证脚本（`measure_encoding.py` 复跑 §1.2 的编码选型实测） |
| `.tmp/dist-p1/_verify/{sizes.json,site_diff.json,measure_encoding.json}` | 体积/对拍/选型证据快照 |
| `reports/index-p1-impl.md` | 本报告 |

---

## 8. 已知风险 / 后续

| 风险 | 说明 | 缓解 |
|---|---|---|
| 解码 bug | 字段/顺序/`q` 处理错会改变结果 | 全量 126,915 条零差异 + 21 查询逐字节对拍 + 自动回退 `index.json` |
| 大小写还原依赖 ASCII | 非 ASCII 大小写映射（ß/İ）构建端直接存完整 `d`，不还原 | 构建端逐字符验证；全量数据已覆盖；新增数据自动走兜底 |
| 解析耗时未下降 | core 仍需 parse+建对象，与旧 `JSON.parse` 相当（207→201 ms） | P2 分片/按需；P1 目标只是传输字节 |
| 丢弃 `f` | 未来若前端要用剂型，需重新加列（+~57 KB gzip） | 已注明；全量对拍证明当前 0 引用 |
| 发布遗漏 core 文件 | app.js 先上线而 core 404 → 每用户回退下 6 MB | 构建一次写全 + `publish.ps1` 全量拷贝；前后端同一次发布；失败仍可用 |
| Pages 不压缩 core | 若未 gzip，15.3 MB 明文比现状更差 | 发布后 curl 验证 `content-encoding: gzip`（见 §6.4）；`?legacy=1` 应急 |
| 首屏 +970 B | 解码器代码 | 可忽略（仍 ≈0.3% 旧首屏） |
| 真机未验 | — | 发布前桌面/手机点测（§6.6） |
