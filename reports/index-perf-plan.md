# 首屏 / 首搜索引性能方案（index.json 34.8 MB → 拆片与压缩）

> 任务：task-2（首屏索引性能）。作者：子智能体 index-perf。
> 分析对象：线上 https://fuarnos.github.io/drug-brand-crossref/ 与本地 `site/dist/data/index.json`（v0.3.3，34,795,787 B / 126,915 键）。
> 约束：本任务只读 `site/build.py`、`site/dist`，未跑 git / 未发布 / 未跑 `site/build.py`；全部原型与测量在 `.tmp/perf/`。
> 测量环境：Windows 10 + Python 3.12（本机）+ Node v22（本机）；Python `gzip -9` 与线上实际传输的校准系数 **×1.041**（见 §2）。

---

## 0. 结论（TL;DR）

| 阶段 | 动作 | 首搜首屏字节 | 完整功能就绪字节 | 首屏（未输入时） | 工作量/风险 |
|---|---|---|---|---|---|
| 现状 | 页面加载即拉全量 index.json | **6.06 MB**（实测） | 6.06 MB | 6.08 MB | — |
| P0 | 索引改为「第一次输入才加载」，aliases/confused 随首搜加载 | 6.06 MB | 6.06 MB | **≈16 KB** | 0.5 小时 / 极低 |
| P1 | index.json → **列式+字典编码单文件**（客户端解码回 `IDX`，功能不变） | **3.93 MB**（预估，-35%） | 3.93 MB | 同现状或 16 KB | 1 天 / 低 |
| **P2（推荐）** | **P1 核心 + 范围分片 + manifest，首搜只拉命中前缀分片**（基线 64 片） | **0.092 MB p50 / 0.12 MB p90**（N=64，-98.5%）；N=32 则 0.18/0.22 MB | +3.93 MB 后台补全 | ≈16 KB | 2–3 天 / 中 |
| P3（可选） | 成分详情文件 `data/sub/<sid>.json` 替代“后台全量核心” | 0.092 MB | **≈0.2 MB**（同成分/国家视图一起解决） | ≈16 KB | 3–5 天 / 中高 |

**推荐落地顺序：P0 → P1 → P2**，P3 作为下一版优化。P2 的收益：首屏字节 **6.06 MB → 0.092 MB（约 1/66）**；每次按键查找从 **102 ms（全量扫描）→ 约 2 ms**（本机 Node 基准，手机约 3–5×）；首屏（用户还没输入时）从 6.08 MB 降到约 16 KB。若不想一次上 64 片，32 片（0.18 MB）已经拿到 -97%。

---

## 1. 现状测量

### 1.1 线上传输实测（`Accept-Encoding` 探测，只读 GET/HEAD）

| 文件 | 线上 Content-Encoding | Content-Length（线上传输） | 解压后 | 结论 |
|---|---|---|---|---|
| `data/index.json` | **gzip** | **6,062,430 B（5.78 MiB）** | 34,795,787 B | Pages 已自动 gzip，压缩率 17.4% |
| `data/aliases.json` | gzip | 18,279 B | 216,064 B | 首搜一起下载，小 |
| `data/artg.json` | gzip | 868,901 B | 4,866,373 B | 已是懒加载（无产品命中时才拉） |
| `data/confused.json` | gzip | 882 B | 3,575 B | 可忽略 |
| `assets/app.js` | gzip | 6,763 B | 16,201 B | — |
| `index.html` | gzip | 1,448 B | 3,700 B | — |

关键事实：
1. **GitHub Pages 只做 gzip，不做 Brotli**：请求头给 `Accept-Encoding: br` 时返回 `Content-Encoding: None` + 34.8 MB 明文；给 `gzip, deflate, br` 时返回 gzip。→ **不要指望 CDN 侧 br**；若要用 br，只能自己预压缩 + 前端 `DecompressionStream`（兼容性差，见 §7）。
2. 首搜实际传输是 **6.06 MB，不是 34.8 MB**；但 34.8 MB 仍要 **下载 6 MB + 解压 34.8 MB + `JSON.parse`**，移动端内存/CPU 才是主要瓶颈（§1.3）。
3. 本机 `gzip -9` 压同一文件得 5,823,313 B，线上 6,062,430 B → **线上动态压缩比 gzip -9 大约 4.1%**。下文所有“预估线上”= 本机 gzip -9 × 1.041（±2–4%）。

### 1.2 页面加载链路（现状 = 首屏即首搜）

`index.html` → `assets/app.js`（末尾代码，build.py 第 733–742 行）：页面一加载就 `Promise.all` 拉 `index.json` + `aliases.json` + `confused.json`，然后 `render()`。也就是说：**用户还没输入任何字，就已经下载 6.06 MB**。当前首屏字节 ≈ 6,062,430（index）+ 6,763（app.js）+ ~6,300（i18n.js）+ 1,467（css）+ 1,448（html）≈ **6.08 MB**。

### 1.3 客户端解析 / 扫描成本（本机 Node 22 基准，Windows 桌面）

| 指标 | 现状全量 index.json |
|---|---|
| 文件字节 / JSON.parse 后条目 | 34.8 MB / 126,915 |
| `JSON.parse` 耗时 | **221 ms**（本机；手机估 0.8–2 s） |
| parse 后 JS 堆 | **84 MB（heapUsed）**，峰值更高（手机易触发 GC/内存压力） |
| 一次首遍扫描（`for(const e of IDX)` + `tier()`） | **102.4 ms / 次输入**（本机；手机 300–500 ms） |
| 模糊兜底第二遍扫描 | 再加约 1 遍全表（≈ 另 100 ms） |

> 现状 `render()` 绑定在 `input` 事件上，**每敲一个键就全表扫一遍**（build.py 第 538、551 行）。这是“移动端卡”的第二个来源，拆片后可降到毫秒级（§4）。

---

## 2. 条目结构与字段体积（`site/dist/data/index.json`）

### 2.1 结构

顶层是 **数组**（不是对象）：`[ {k,d,c,x,s,f,l,n,v,vs,u,g,gn,m,mn[,q]}, ... ]`，126,915 条；其中 163 条多一个 `q`（加拿大数字/符号开头残名降权标记）。键顺序固定，`separators=(",",":")` 紧凑输出（build.py 第 1863–1865 行）。

| 字段 | 含义 | 序列化字节 | 占比 | 客户端是否使用 |
|---|---|---:|---:|---|
| `d` | 展示名（原始大小写） | 3,975,823 | 11.43% | 是（结果行） |
| `k` | 检索键（归一化小写） | 3,556,619 | 10.22% | 是（匹配） |
| `x` | 成分展示串（最多 6 个，` + ` 连接） | 3,372,300 | 9.69% | 是 |
| `m` | 主要上市许可持有人（MAH）名 | 3,268,281 | 9.39% | 是 |
| `vs` | 多成分 id 列表（37,399 条非空） | 2,455,461 | 7.06% | 是（同成分/国家解析） |
| `v` | 主成分 id | 2,030,026 | 5.83% | 是 |
| `s` | 剂量串数组（0–6 个） | 1,831,674 | 5.26% | 是 |
| `f` | 剂型 | 1,135,954 | 3.26% | **否（app.js 中 0 处引用）** |
| `c` | 国家码数组（1–6 个） | 812,825 | 2.34% | 是 |
| `l` | 碰撞等级（3 种） | 795,014 | 2.28% | 是（徽标） |
| `u` | 独立名称页文件名（17,868 条非空） | 632,785 | 1.82% | 是（链接） |
| `gn` | 品牌族说明（9 条非空） | 254,918 | 0.73% | 是 |
| `g` | 品牌族标签（9 条非空） | 253,948 | 0.73% | 是 |
| `n` | 包装/产品数（排序权重） | 135,107 | 0.39% | 是（排序） |
| `mn` | MAH 数量 | 130,873 | 0.38% | 是（显示 +N） |
| `q` | 降权标记（163 条） | 163 | ~0% | 是（排序） |
| 合计 | — | 34,795,787 | 100% | `f` 是唯一可删字段 |

### 2.2 名字 / 别名长度分布

- `k` 平均 **26.0 字节**（UTF-8；中文 3 字节/字），中位 ~17 字符，最长 419；`k` 总字节 3,302,784。
- `d` 长度分布与 `k` 基本一致（`d.lower()==k` 的有 74,609 条，`d==k` 13,937 条）。
- `x`：中位 10 字符，长尾到 562 字符（复方成分串）。
- `s` 个数：0 个 23,921 条 / 1 个 54,494 / 2 个 22,614 / ≥3 个 25,886。
- `c` 个数：1 国 121,145 条、2 国 3,348、≥3 国 2,422。
- `aliases.json`：**422 条**，216,064 B（gzip 17,725 B）；字段 15 个（`a,n,v,i,x,k,cf,hint,src,m,me,ct,su,c,np`），每条都全字段存在（冗余大，但总量小）。
- `artg.json`：34,594 行、4,866,373 B（gzip 845,479 B），已懒加载。

### 2.3 首字符分布（决定分桶粒度）

ASCII 首字母占绝大多数：`a` 12,452、`c` 10,475、`s` 9,917、`p` 7,996、`b` 7,236、`m` 6,741 …；数字/符号 583；**CJK 开头仅 11,680 条，但分散在 954 个不同首字**（最高「盐」670、「注」658、「复」519）。

→ 因此**不建议“按首字母分文件”**（CJK 会出现 954 个碎片或 1 个巨大 misc 桶）；改用 **按 `k` 排序后的等体积范围分片 + manifest 边界二分**：每片大小均匀、前缀查询天然对应 1–2 片、CJK/拉丁统一处理。首字符分布只用来解释为什么“a”开头的分片最热。

字面“按首字母/CJK 首字分桶”也做了实测（`firstletter_proto.py`）：**981 个文件**（26 字母 + 数字符号 + 954 个 CJK 首字），manifest 9.7 KB gz，全部桶 gzip 合计 **6.24 MB（比整文件 5.82 MB 还大 7%）**；拉丁桶极不均衡——`a` 桶 615,773 B gz、`c` 桶 522,620、`s` 桶 493,219，按真实查询模拟**拉丁 exact/prefix 首屏 p50 296 KB / p90 625 KB**；CJK 侧则相反（954 个桶 p50 仅 337 B gz，中文首屏 p50 12 KB）。即：字面首字母分桶 “CJK 极省、拉丁极亏”，且文件数近千、总体积更大。范围分片用一套代码取得均衡（§3.4），若想再拿 CJK 的低首屏，可把“等字节切分”改成“**按密度自适应切分**”（CJK 区间片更细、拉丁区间片更粗，见 §3.4 末尾），客户端二分代码不变。

> 安全前提已验证：**所有 126,915 个键都不含 emoji/星平面字符（无 >U+FFFF 码点）**，Python `sorted()` 与 JS 字符串 `<` 比较顺序一致，manifest 二分在客户端可精确复现。

---

## 3. 原型与测量（`.tmp/perf/`）

### 3.1 原型脚本

| 脚本 | 作用 | 产物 |
|---|---|---|
| `.tmp/perf/analyse_index.py` | 字段字节占比、字典化潜力、长度分布、首字符分布、压缩参考 | `analysis.json` |
| `.tmp/perf/online_probe.py` | 线上 gzip/br/identity 实测（只读） | `online_probe.json` |
| `.tmp/perf/build_proto.py` | 生成 V1 裁剪 / V2 行数组 / V3 列式字典 / V4 keys 核心 / V5 分片（N=16/32/64）+ manifest | `out/`、`measure.json` |
| `.tmp/perf/extra_measure.py` | 列式核心按 `k` 排序、`d` 增量、首页静态资源 | `extra_measure.json` |
| `.tmp/perf/bench_node.js` | 用 Node 复刻 `tier()/norm()`，模拟 257 条真实查询：前缀快路径字节、命中完整度、fallback 字节、parse/扫描延迟 | `node_bench.json` |
| `.tmp/perf/firstletter_proto.py` | 对比方案：字面「按首字母 / 数字 / CJK 首字」分桶（981 桶）体积与首屏字节 | `firstletter.json` |
| `.tmp/perf/shard_compare.py` | 用真实查询集比较 N=16/32/64 范围分片的首屏字节 | `shard_compare.json` |
| `.tmp/perf/sub_estimate.py` | P3 设想：按成分拆 `sub/<sid>.json` 的体积外推 | `sub_estimate.json` |

复现：
```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\perf\analyse_index.py
& $py .tmp\perf\online_probe.py
& $py .tmp\perf\build_proto.py
& $py .tmp\perf\extra_measure.py
$node = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
& $node --max-old-space-size=4096 .tmp\perf\bench_node.js
```

### 3.2 单文件方案体积对比（本机 gzip -9；*预估线上 = ×1.041*）

| 方案 | raw | gzip -9 | *预估线上* | 相对现状 | 说明 |
|---|---:|---:|---:|---:|---|
| V0 现状 | 34,795,787 | 5,823,313 | 6,062,430（实测） | — | 数组 of 对象 |
| V1 删 `f` | 33,025,258 | 5,680,891 | ≈5.91 MB | -2.2% | **只删字段，客户端零改动**（`f` 未用） |
| V2 行数组（每行一个数组，去掉重复字段名） | 26,170,468 | 5,396,852 | ≈5.62 MB | -7.3% | 需 30 行解码 |
| V3 列式+字典（原顺序） | 16,175,813 | 4,163,466 | ≈4.33 MB | -28.5% | 结构重写，解码 ~40 行 |
| **V3b V3 且按 `k` 排序** | 16,031,541 | **3,774,727** | **≈3.93 MB** | **-35.2%** | P1 推荐形态 |
| V3c V3b + `d` 增量（`d==k` 时存空串） | 15,795,356 | 3,701,578 | ≈3.85 MB | -36.4% | 额外 -2%，可并入 P1 |

列式编码规则（V3b）：`k,d,n,mn,u` 存原始数组；`c,x,s,l,v,vs,g,gn,m` 字典编码（dict + 整数索引，字典量见 `analysis.json`：`x` 20,793 种、`s` 23,679 种、`m` 13,554 种、`c` 仅 70 种、`l` 3 种）；`q` 存稀疏下标。

### 3.3 keys 核心（contains/fuzzy 兜底匹配用）

| 文件 | raw | gzip -9 | *预估线上* |
|---|---:|---:|---:|
| `keys.json`（仅 k，已按 k 排序） | 3,683,535 | 866,929 | ≈0.90 MB |
| `keys_nl.txt`（换行分隔） | 3,432,777 | 853,479 | ≈0.89 MB |
| `keys+n+v` 列式（k/n/v，v 用于定位成分详情） | 6,102,516 | 1,273,804 | ≈1.33 MB |

### 3.4 分片方案（P2）：按 `k` 排序后等字节范围切成 N 片

每片为完整条目对象数组（客户端可复用现有 render 代码），另加 `manifest.json`（每片 `first/last/n/bytes/gz`）。

| N | 文件数 | manifest gzip | 单片 gzip 中位 | 最小 / 最大 | 全部片合计 gzip | 首屏字节 p50 / p90（真实查询模拟） |
|---:|---:|---:|---:|---:|---:|---:|
| 16 | 16 | 980 B | 339,874 | 321,967 / 396,692 | 5,458,202 | 342 KB / 365 KB |
| 32 | 32 | 1,494 B | 169,762 | 153,428 / 208,769 | 5,466,724 | 172 KB / 190 KB |
| **64** | **64** | **2,755 B** | **85,606** | 70,825 / 117,765 | 5,488,149 | **88.6 KB / 97.2 KB** |

（模拟方法与 `bench_node.js` 一致：首屏字节 = manifest gz + 与 `[nq, nq+'\uffff']` 相交的全部片的 gz；明细见 `shard_compare.json`。）

- 分片总和（5.46–5.49 MB gzip）和整文件（5.82 MB）几乎一样，**拆片不增加总数据量**（按范围各自压缩反而略小）。
- **首屏字节 = manifest + 命中前缀范围的片**（前缀 `nq` 对应 `[nq, nq+'\uffff']`，与片 `[first,last]` 求交，一般 1 片，跨边界 2 片）。
- 推荐 **N=64**：首屏 p50 **88.6 KB**（线上 ≈92 KB，-98.5%），65 个新文件，每次发布 git 增长约 5.5 MB（gz）；N=32 是更稳的折中（172 KB、33 个文件）。
- **可选的 P2b「按密度自适应切分」**：把总字节切成“拉丁区间 ~80–90 KB gz/片、CJK 区间 ~15–20 KB gz/片”（CJK 段 11,680 条 ≈3 MB raw，可切 ~64 片），预计文件数 ~130、中文首屏降到 ~20 KB、拉丁维持 ~90 KB；**客户端二分逻辑完全不变**，只是 manifest 边界不同。这是把 §2.3 首字母分桶里“CJK 很省”的优点并进来、而不背它“拉丁很亏 + 981 文件”的缺点。
- 更激进的拉丁切分（目标 40–50 KB gz/片）可把首屏压到 ~50 KB，代价是 ~200 个文件；按移动端首屏预算 100 KB 左右，N=64 已经够用。

### 3.5 查询模拟（Node，257 条查询；主表 N=32，附 N=64）

| 查询类型 | 条数 | 快路径字节 p50（N=32） | p90（N=32） | 快路径字节 p50（N=64） | p90（N=64） | 分片数 p50 | 首屏结果完整度 p50 | 结论 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| exact（完整品牌名） | 60 | 171,785 | 189,878 | **88,566** | 97,203 | 1 | **100%** | 快路径即可直接出完整结果 |
| prefix（拉丁 4 字符） | 60 | 170,726 | 183,060 | 89,925 | 156,666 | 1 | 39.1% | 前缀命中完整，缺跨片 `contains` 命中 → 后台补全 |
| prefix-cjk（中文 2 字） | 35 | 190,557 | 210,263 | 98,005 | 120,520 | 1 | **100%** | 快路径完整 |
| exact-cjk（完整中文名） | 20 | 190,557 | 210,263 | 98,005 | 120,520 | 1 | **100%** | 快路径完整 |
| contains（拉丁 4 字符子串） | 38 | 171,785 | 178,761 | 89,830 | 93,278 | 1 | 1.2% | 必须走完整核心 |
| contains-cjk（中文 2 字子串） | 17 | 190,557 | 210,263 | 97,203 | 120,520 | 1 | 42.9% | 必须走完整核心 |
| fuzzy（错字） | 27 | 169,405 | 183,060 | 88,566 | 95,490 | 1 | —（模糊只在兜底遍） | 必须走完整核心 |

- **首屏（前缀快路径）总字节：N=32 时 p50 175,269 / p90 210,263 / max 344,028 B；N=64 时 p50 88,566 / p90 97,203 / max 120,520 B（本机 gzip 合计）→ 预估线上 N=64 p50 ≈92 KB / p90 ≈101 KB。**
- 解析延迟（Node 本机）：单片 `JSON.parse` 中位 **4.9 ms**（首片 JIT 冷启 45 ms；N=64 片更小，约 2–4 ms）；前缀片局部扫描平均 **2.9 ms**（N=64 约 1.5–2 ms）；对比现状全量 parse 221 ms + 扫描 102 ms。
- 对“快路径结果不完整”的说明：现状第一遍扫描会同时收 `exact/compact/prefix/contains/fuzzy-除外` 四类命中（build.py 第 538–549 行），其中 `contains` 命中可能在任意分片。P2 的界面上先显示前缀命中（标“完整索引加载中…”），核心到达后重跑完整 render；exact/中文前缀两类本来就 100% 完整，体验损失很小。
- 备用兜底（不推荐）：实测“keys 核心(1.33 MB) + 对 top-40 命中逐个找分片拉详情”的 fallback 字节 p50 1.78 MB / p90 3.94 MB / max 4.84 MB——**因为 top-40 命中散落在最多 32 个分片里**，比直接等 3.93 MB 的核心更差。→ 硬查询（contains/fuzzy/国家/同成分）统一走“后台核心”，不要走 keys+分片拼装。

### 3.6 P3 设想（可选，下一版）：按成分拆详情文件

`sub_estimate.py` 外推：把每条条目复制到它的每个成分文件 `data/sub/<sid>.json`（12,868 个文件、207,991 条引用、raw 合计 65.9 MB、估算 gzip 合计 11.6 MB；单文件中位 raw 769 B / gzip 304 B，p90 6.7 KB / 1.2 KB，最大 2.0 MB；品牌族仅 4 组 9 条 → `fam.json` 约 4 KB）。

用途：精确/前缀命中后，“同成分其他商品”“切换国家显示”都只需拉 1–6 个几 KB 的成分文件，**不再需要下载 3.93 MB 全量核心**；contains/fuzzy 兜底 = `keys+n+v`（1.33 MB）+ top-40 命中的成分文件（每个命中一个成分文件，约 40 × 0.3–1.2 KB ≈ 20–50 KB）≈ **1.4 MB**。代价：dist 文件数 30,755 → 43,623、raw 体积 +66 MB（Pages 1 GB 仍宽裕，但 publish 拷贝/Pages 部署变慢），需另立任务。

---

## 4. 推荐方案（P0 + P1 + P2）

### 4.0 目标与验收数字

1. **首搜首屏字节：6,062,430 → 约 92,000 B（p50）/ 约 101,000 B（p90）**（N=64，即 **-98.5%**；保守用 N=32 则 182,500 / 219,000 B，-97%）；
2. **首屏（未输入）：6.08 MB → 约 16 KB**；
3. 单次按键查找：102 ms → 约 2 ms（本机）；移动端从 300–500 ms → 约 10–20 ms；
4. 完整功能（contains/fuzzy/国家/同成分/品牌族）在首屏后由后台核心补全，**行为与今天一致**；核心未到期间显示“完整索引加载中…”且只降级“跨条目区块”，不降级前缀/精确结果；
5. 任一分片/核心请求失败 → 自动退回现全量 `data/index.json`（保留一个版本，见 §5.3 回滚）。

### 4.1 P0：把索引改成“第一次输入才加载”（0.5 小时，极低风险）

- `app.js`（build.py 第 733–742 行）：页面加载只 fetch `manifest`/aliases/confused，**不再 fetch `index.json`/`core.json`**；`box.addEventListener('input', onInput)`，首个非空输入时才进入加载流程。
- 首页字节 6.08 MB → ≈16 KB；对“打开就走”的访客不再消耗流量。
- 同时建议：`input` 加 120–150 ms debounce（现状每键全表扫描，P0 后仍会每键扫全量，直到 P2 才解决）。

### 4.2 P1：列式+字典编码单文件核心（1 天，低风险；P2 的基础）

- 新增构建产物 `data/idx/core.json`（V3b，≈16.0 MB raw / 3.93 MB 线上 gzip），**功能完全等价**：客户端 30–40 行 `decodeColumnar()` 把它还原成现有的 `IDX` 数组（对象结构不变），`render()` 以下逻辑一行不改。
- 保留旧 `data/index.json` 至少一个版本（双写，rollback + 失败兜底）。
- 收益：首搜 6.06 MB → 3.93 MB（-35%）；`JSON.parse` 34.8 → 16.0 MB（本机 221 → ~100 ms），JS 堆显著下降。
- 预期可独立上线、可独立回滚，先落这个再谈分片。

### 4.3 P2：manifest + 64 片范围分片 + 两段式渲染（2–3 天，中风险；推荐主形态）

构建产物（每次 build 同时写）：
```
data/index.json                  # 保留（旧版回滚 / 兜底，双写）
data/idx/manifest.json           # ~8 KB raw / 2.8 KB gz：版本、片数、每片 first/last/n/bytes/gz、core 大小
data/idx/core.json               # P1 列式核心（后台加载）
data/idx/s00.json … s63.json     # 64 片完整条目，按 k 排序、等字节切分（合计 34.8 MB raw / 5.49 MB gz）
```
客户端流程（`app.js`）：
1. 页面加载：`manifest` + `aliases` + `confused`（≈20 KB）；
2. 第一次输入：`norm()`/`splitDose()` 后，按 manifest 二分出 `[nq, nq+'\uffff']` 相交的分片 → fetch（1–2 片）→ 用现有 `tier()` 在前缀片内跑第一遍扫描 → 立刻渲染（`partial=true`：跳过昵称产品列表/国家视图/同成分/品牌族/模糊，meta 显示“完整索引加载中…”）；
3. 同一时刻后台 `loadCore()`（P1 核心 3.93 MB，或 P3 后改为按需拉成分文件）→ 解码成 `IDX` → 重跑 `render()`，所有区块恢复；
4. 硬查询（contains/fuzzy）或用户选了国家且核心未到：显示“正在加载完整索引…”（若前缀片已有局部结果则先显示）；
5. 任一请求失败/超时 → 回退 fetch `data/index.json` → 旧逻辑。

> 说明：为什么不是“按首字母/CJK 首字分桶”——CJK 954 个首字必须再合并，合并规则的复杂度高于排序后范围分片；且范围分片对“前缀”语义天然精确（`startsWith` 的前缀集合在排序数组中必然连续），CJK 与拉丁用同一套代码。

---

## 5. 具体改造步骤（伪代码级）

### 5.1 `site/build.py`

改动点全部在“写出数据文件”段（第 1859–1884 行），`load_index()`（第 959 行）与 SQL 不用动：

```python
# ── 现有（保留双写）──────────────────────────────────────────────
entries = load_index(db)                                        # 第 1862 行
(OUT / "data" / "index.json").write_text(                       # 第 1863–1865 行
    json.dumps(entries, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

# ── 新增 ────────────────────────────────────────────────────────
FIELDS = ["k","d","c","x","s","l","n","v","vs","u","g","gn","m","mn"]
DICT_COLS = {"c","x","s","l","v","vs","g","gn","m"}
IDX_DIR = OUT / "data" / "idx"
IDX_DIR.mkdir(parents=True, exist_ok=True)

def encode_core(rows):           # P1：列式+字典；rows 先按 k 排序利于 gzip
    rows = sorted(rows, key=lambda e: e["k"])
    cols = {}
    for f in FIELDS:
        vals = [e.get(f) for e in rows]
        if f in ("c", "s", "vs"):
            vals = [json.dumps(v, ensure_ascii=False, separators=(",", ":")) for v in vals]
        if f in DICT_COLS:
            uniq = list(dict.fromkeys(vals)); pos = {u: i for i, u in enumerate(uniq)}
            cols[f] = {"d": uniq, "i": [pos[v] for v in vals]}
        else:
            cols[f] = vals
    return {"v": 1, "n": len(rows), "cols": cols,
            "q": [i for i, e in enumerate(rows) if e.get("q")]}

def dump(p, obj, gz=False):
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    p.write_bytes(raw)
    if gz:                                    # 可选：预压缩 + DecompressionStream
        (p.with_suffix(".gz")).write_bytes(gzip.compress(raw, 9))
    return len(raw)

core = encode_core(entries)
core_size = dump(IDX_DIR / "core.json", core)

# P2：按 k 排序后等字节切 64 片（想保守可改 32；首屏字节见 §3.4）
N_SHARDS = 64
rows = sorted(entries, key=lambda e: e["k"])
sizes = [len(json.dumps(e, ensure_ascii=False, separators=(",", ":")).encode()) for e in rows]
target, cur, acc, shards = sum(sizes) / N_SHARDS, [], 0, []
for i, e in enumerate(rows):
    cur.append(e); acc += sizes[i] + 1
    if acc >= target and len(shards) < N_SHARDS - 1 and (len(rows) - i - 1) >= (N_SHARDS - len(shards) - 1):
        shards.append(cur); cur, acc = [], 0
if cur: shards.append(cur)

manifest = {"v": 1, "n": len(rows), "nshards": len(shards),
            "core": {"f": "core.json", "bytes": core_size}, "shards": []}
for si, s in enumerate(shards):
    fn = f"s{si:02d}.json"
    b = dump(IDX_DIR / fn, s)
    manifest["shards"].append({"f": fn, "first": s[0]["k"], "last": s[-1]["k"],
                               "n": len(s), "bytes": b,
                               "gz": len(gzip.compress(json.dumps(s, ensure_ascii=False,
                                        separators=(",", ":")).encode(), 9))})
dump(IDX_DIR / "manifest.json", manifest)
```

要点/坑：
- `entries` 原列表顺序（按 n 降序）不要改：`build_index_page()`（第 1393 行）只用 `stats`，但 `build_name_pages()`（第 1320 行）用 `entries` 生成 `displays` 字典；为稳妥，**排序只作用于副本**，原 `entries` 保持原顺序写 `index.json`。
- 字典列的 `json.dumps(vs)` 先序列化成字符串，客户端 decode 时对 `c/s/vs` 三列 `JSON.parse` 回数组（约 126,915×3 次小 parse，本机实测可接受；或直接存数组，体积 +~0.6 MB gz，实现更简单——二选一）。
- `manifest` 的 `first` 必须与 `sorted()` 完全一致（Python 与 JS 在这个数据集上顺序一致，已验无星平面字符）。
- 版本号：manifest 里带 `CHANGELOG` 版本或 `int(time.time())`，`app.js` 的 `?v=` 一次取到。

### 5.2 `site/build.py` 内嵌的 `app.js`（`APP_JS`，第 409 行起）

**(a) 全局状态与加载器**（替换第 417 行 `let IDX = [], ...` 与第 733–742 行加载块）：

```js
let IDX = null;              // 完整条目（核心解码后）——原逻辑全部照旧
let NICKS = [], CONF = [];
let MANIFEST = null, CORE_P = null;
const SHARD_CACHE = new Map();

function loadManifest(){
  return fetch(BASE + 'data/idx/manifest.json?v=' + V)
    .then(r => { if (!r.ok) throw 0; return r.json(); }).then(m => (MANIFEST = m));
}
function shardsForPrefix(nq){                 // 与 [nq, nq+'\uffff'] 相交的片
  if (!MANIFEST) return [];
  const S = MANIFEST.shards, hi = nq + '\uffff';
  let out = [];
  for (let i = 0; i < S.length; i++) {
    if (S[i].first > hi) break;
    if (S[i].last >= nq) out.push(S[i]);
  }
  return out;
}
function fetchShard(s){
  if (SHARD_CACHE.has(s.f)) return Promise.resolve(SHARD_CACHE.get(s.f));
  return fetch(BASE + 'data/idx/' + s.f + '?v=' + V).then(r => r.json())
    .then(d => { SHARD_CACHE.set(s.f, d); return d; });
}
function loadCore(){                          // 后台补全
  if (IDX) return Promise.resolve(IDX);
  if (!CORE_P) CORE_P = fetch(BASE + 'data/idx/core.json?v=' + V)
    .then(r => r.json()).then(decodeColumnar)
    .then(d => { IDX = d; return d; });
  return CORE_P;
}
function decodeColumnar(c){                   // ~35 行：列 → 对象数组
  const n = c.n, out = new Array(n), C = c.cols;
  for (let i = 0; i < n; i++) out[i] = {};
  for (const f in C) {
    const col = C[f];
    if (col.d) { const idx = col.i; for (let i = 0; i < n; i++) out[i][f] = col.d[idx[i]]; }
    else if (f === 'q' && Array.isArray(col)) { for (const i of col) out[i].q = 1; }
    else { for (let i = 0; i < n; i++) out[i][f] = col[i]; }
  }
  for (let i = 0; i < n; i++) {               // c/s/vs 若按 JSON 字符串存，这里还原成数组
    for (const f of ['c', 's', 'vs']) {
      const v = out[i][f];
      if (typeof v === 'string') out[i][f] = JSON.parse(v);
    }
  }
  return out;
}
async function legacyLoadIndex(){              // 失败兜底 / 回滚
  IDX = await fetch(BASE + 'data/index.json?v=' + V).then(r => r.json());
  render();
}
```

**(b) `render()` 改造**（第 513 行的函数；最小 diff 做法）：

```js
let SHARD_POOL = null;                        // 当前前缀片条目（仅快路径用）

async function onInput(){
  const q = box.value.trim();
  if (!q) { /* 原清空逻辑 */ return; }
  const nq = norm(splitDose(q)[0]);
  if (!IDX) {                                 // 阶段 A：快路径
    try {
      if (!MANIFEST) await loadManifest();
      const ss = shardsForPrefix(nq);
      if (ss.length) {
        const parts = await Promise.all(ss.map(fetchShard));
        SHARD_POOL = parts.flat();
        renderWith(SHARD_POOL, /*partial*/ true);   // 只渲染前缀/精确/连写命中
        loadCore().then(() => renderWith(IDX, false)).catch(legacyLoadIndex);
        return;
      }
    } catch (e) { /* fall through */ }
    out.innerHTML = '<div class="sub">Loading full index… 正在加载完整索引</div>';
    try { await loadCore(); renderWith(IDX, false); } catch (e) { legacyLoadIndex(); }
    return;
  }
  renderWith(IDX, false);                     // 原全量逻辑
}
```

`renderWith(pool, partial)`：把现 `render()` 里所有 `IDX` 引用（第 538、551、572、652、676 行）替换为 `pool`；`partial === true` 时：
- 跳过昵称产品展开、`inCountry` 国家视图（第 572 行）、品牌族（第 652 行）、同成分（第 676 行）、模糊兜底（第 551 行）；
- `meta` 末尾追加 `T('res.loading_full')`（新增 i18n 键，zh/en/es 三份）；
- 其余（结果表、剂量排序、昵称提示、易混淆提示）照旧。
> 也可以更省事：`partial` 时只渲染结果表 + 一条“完整索引加载中…”，核心到达后重跑完整 `render()`。

**(c) 事件绑定**：`box.addEventListener('input', debounce(onInput, 120))`；`ctry` change 时若 `!IDX` 先显示等待再触发 `loadCore`。

**(d) 回滚开关**：URL 加 `?legacy=1` 时直接 `legacyLoadIndex()`；或发布时保留上一版 `app.js`（`assets/app.legacy.js`）供快速切回。

### 5.3 发布与回滚

- **发布**：一次 build 多写 65 个文件（64 片 + manifest）+ `core.json`；`deploy/publish.ps1` 的既有检查（`data/index.json` ≥5 MB、文件数 ≥24,000、无 0 字节）仍全部通过（因为保留 index.json），**不需改 publish.ps1**。
- **回滚**：三个层次——① URL `?legacy=1` 走旧全量；② 前端 fetch 分片失败自动回退 `index.json`；③ 发布回滚 = `gh-pages` revert 到上一提交（保留 index.json 使③无需重建数据）。
- **弃用旧文件**：稳定一个版本后若要删 `index.json`，必须同步改 `publish.ps1`（第 114–116 行的 ≥5 MB 检查）——跨文件工作，**另立任务**，不在本方案范围内。

---

## 6. 预期收益对照

| 指标 | 现状 | P0 | P1 | **P2（推荐）** |
|---|---:|---:|---:|---:|
| 首屏（未输入）传输 | 6.08 MB | **≈16 KB** | ≈16 KB | ≈16 KB |
| 首搜首屏字节（出结果） | 6.06 MB | 6.06 MB | 3.93 MB | **0.092 MB p50 / 0.12 MB p90**（N=64；N=32 为 0.18/0.22） |
| 完整功能就绪字节 | 6.06 MB | 6.06 MB | 3.93 MB | 0.09 + 3.93（后台）|
| 首屏后是否阻塞 | 是（parse 221 ms/手机更久） | 是 | parse ~100 ms | **否**（片 parse 2–4 ms + 扫描 2 ms） |
| 每次按键扫描 | 102 ms | 102 ms | 102 ms | **≈2 ms**（快路径） |
| index 解析体积/内存 | 34.8 MB / 堆 84 MB | 同 | 16.0 MB / 约一半 | 片 ~0.55 MB / 后台核心 16 MB |

---

## 7. 兼容性与风险清单

| 风险 | 说明 | 缓解 |
|---|---|---|
| 列式解码 bug（P1） | 字段顺序/稀疏 `q` 处理错会导致结果错 | decode 后与旧 index.json 抽样对拍（造 500 条随机条目比较 JSON 等值）；先上 P1 保留双写 |
| 快路径结果不完整（P2） | 拉丁 4 字前缀有跨片 `contains` 命中缺失；contains/fuzzy 必须等核心 | 显式“完整索引加载中…”提示；exact/中文前缀本就完整；核心到后自动重渲 |
| manifest 二分与排序不一致 | 客户端 `<` 是 UTF-16 序，Python 是码点序 | 已验证无星平面字符（§2.3）；构建时加断言 `assert all(ord(c)<=0xFFFF …)` |
| 分片请求失败/超时 | 移动网络抖动 / Pages 404（构建不完整） | try/catch → 回退 `index.json`；publish.ps1 已有完整性检查 |
| GitHub Pages 压缩 | 分片/核心是否也自动 gzip 未线上验证 | 首次发布后用 `curl -H 'Accept-Encoding: gzip' -I` 逐个确认 `content-encoding: gzip`；不 gzip 则回退 P1 单文件 |
| Pages 只 gzip 不 br | 预压缩 `.br` 需前端 `DecompressionStream`（Safari <16.4 不支持） | 本方案不依赖 br；预压缩仅作可选优化且必须有明文回退 |
| `?v=timestamp` 缓存破坏 | 每次发布所有分片/核心重新下载 | 短中期可接受；长期改成内容哈希目录 + 保留旧目录一版 |
| 移动端内存 | P2 解码核心后仍会建 126,915 个对象（≈84 MB 堆） | 核心延迟解码；P3/后续可改成“列访问器”避免建对象；先按 P2 实测再定 |
| 构建/发布耗时 | dist raw 128 MB → 163 MB（P2）；文件数 +65 | Pages 1 GB 上限宽裕；publish 拷贝 +~35 MB，预计 +10–20 秒 |
| 回滚面 | 前端两个文件（app.js + 数据文件） | 保留 index.json 双写 + `?legacy=1` + gh-pages revert 三层 |

---

## 8. 发布影响（文件数 / Pages 限制）

| 项 | 现状 | P1 | P2 | P3（可选） |
|---|---:|---:|---:|---:|
| `site/dist` 文件数 | 30,755 | 30,756 | **30,820** | 43,623 |
| `site/dist` raw 体积 | 128.0 MB | 144 MB | **163 MB** | 229 MB |
| gh-pages 每次发布数据增量 | 5.8 MB gz | ~9.7 MB gz | ~15.1 MB gz | ~26 MB gz |
| GitHub Pages 限制 | 1 GB 站点 / 100 GB 月流量 / 10 次构建每小时 | 全部宽裕 | 全部宽裕 | 文件多但仍在常规范围 |

- Pages 是 CDN 分发的，多 65–100 个文件对 TTFB 影响可忽略（HTTP/2 多路复用）。
- **bandwidth 账**：现状每次“首搜”约 6.06 MB；P2 典型前缀/精确搜索首屏 **0.09 MB** + 后台核心 3.93 MB ≈ **4.02 MB（-34%）**；若采用 P3（成分详情文件）则典型搜索 ≈ 0.1–0.2 MB（-97%）。
- 构建时间：多写 65 个 JSON（~35 MB）+ 1 个核心（16 MB），gzip 计算如果不在构建里做（让 Pages 动态压缩）则只多几秒写盘。

---

## 9. 未采用的替代方案（附实测依据）

| 方案 | 实测/理由 | 判定 |
|---|---|---|
| 只删字段 `f` | 本机 gzip 5.82 → 5.68 MB（-2.2%）；raw -5% | 可作为 P0 顺手做，不足以解决问题 |
| 行数组（去字段名） | gzip -7.3% | 收益/改动比不如列式字典 |
| 预压缩 `.json.gz`（gzip） | 本机 gzip -9 = 5,823,313 vs 线上 6,062,430，省 ~0.24 MB（4%），但要 `DecompressionStream` + 兼容回退 | 可选微优化；**P2 后更值得**（省的是分片/核心的 4%） |
| Brotli 预压缩 | Pages 不支持 br；自行解压需 `DecompressionStream('br')`（浏览器支持面窄） | 不建议 |
| 按首字母分桶 | 实测 981 个文件、总 gzip 6.24 MB（比整文件大 7%）、拉丁首屏 p50 296 KB / p90 625 KB（`a` 桶 616 KB）；CJK 侧 p50 仅 12 KB | 不采用（§2.3）；把其中“CJK 细片”优点吸收成 P2b 自适应分片 |
| keys 核心 + 命中分片拼详情 | 实测 fallback p50 1.78 MB / p90 3.94 MB，因为 top-40 命中散落在多片 | 不采用；硬查询统一等后台核心 |
| Service Worker 缓存 | 只帮回访，不帮首访；且需要 HTTPS（Pages 满足） | 可作为 P4 增量（回访 0 网络） |
| 拆成 per-ingredient 详情文件 | 12,868 文件、raw +66 MB；但能把完整路径从 3.93 MB 降到 ~0.2 MB | **P3 候选**，需单独立项 |

---

## 10. 交付物清单

| 路径 | 内容 |
|---|---|
| `reports/index-perf-plan.md` | 本报告 |
| `.tmp/perf/analyse_index.py` + `analysis.json` | 字段占比、字典潜力、长度/首字符分布 |
| `.tmp/perf/online_probe.py` + `online_probe.json` | 线上 gzip/br/identity 实测数据 |
| `.tmp/perf/build_proto.py` + `measure.json` + `out/` | V1/V2/V3/V4/V5 原型产物与体积测量（`out/shards32/` + `manifest16/32/64.json` 供复跑模拟；`out/v3_core.json` 为 P1 核心样本） |
| `.tmp/perf/extra_measure.py` + `extra_measure.json` | 列式核心排序/增量优化、首页静态资源 |
| `.tmp/perf/bench_node.js` + `node_bench.json` | 257 条查询的字节/完整度/延迟模拟明细 |
| `.tmp/perf/firstletter_proto.py` + `firstletter.json` | 首字母/CJK 首字分桶对比（981 桶）实测 |
| `.tmp/perf/shard_compare.py` + `shard_compare.json` | N=16/32/64 分片首屏字节对比 |
| `.tmp/perf/sub_estimate.py` + `sub_estimate.json` | P3 成分详情文件体积外推 |
