# 搜索增强基准 + 客户端检索库对比（task-20）

> 日期：2026-10-27 · 任务：task-20 · 写范围：`.tmp/search-bench/`、本报告
> 未改 `site/build.py`、`site/dist`、`data/drugs.db`；未跑 git / 发布 / 站点构建。
> 基准：`tests/trilingual/run_tests.py` 的 **354 条查询**（123 en / 116 es / 115 zh，72 案例）+ **30 条新增难例**；语料：`site/dist/data/index.json`（126,915 名键，34.79 MB）。
> Node：`C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe`（v24.21.0）；库版本：MiniSearch 7.2.0 / FlexSearch 0.8.212 / @orama/orama 3.1.18 / Fuse.js 7.5.0 / pinyin-pro 3.29.5（装在 `.tmp/search-bench/node_modules`，仅原型用）。
> 审计时 `site/build.py` 正被其他任务修改（当前 sha256 `6f76cd5d…`，2,767 行）；本报告行号以该快照为准，**动工前请重新 grep 函数名**。

---

## 0. 结论（TL;DR）

1. **不建议引入任何第三方检索库**：为等价功能，索引体积会额外增加 **1.10 MB（Fuse）→ 5.68 MB（MiniSearch）→ 12.39 MB（FlexSearch）→ 23.22 MB（Orama）gzip**，全部叠加在必要的 3.86 MB 显示核心之上；且 CJK 精度普遍低于现状（zh Top-1 80.9%–94.8% vs 现状 99.1%）。
2. **推荐「运行时派生匹配层」**：exact/prefix/CJK-bigram/拉丁-trigram+编辑距离 全部在浏览器内从已下载的 P1 核心（`data/idx/core.json`，3.84 MB gz）**零新增下载**派生（一次性构建 0.68 s，可 idle 调度）；唯一需新增下载的是**拼音表 0.39 MB gz**（按需懒加载，且已用 15.9 KB 汉字表验证可由 stdlib 构建）。
3. **指标（桌面 Node 基准）**：
   - 首搜体积：现状 P1 路径 **3.86 MB**（不变；legacy `?legacy=1` 仍 6.08 MB）；拼音查询额外的 0.39 MB 只在首次拼音查询时下载。
   - 每次按键匹配延迟：**P50 73.5 ms → 0.007 ms，P90 104.8 ms → 0.073 ms，P99 ≈ 6.4 ms**（最坏 8.4 ms，为 trigram+编辑距离的 typo 路径；当前模糊兜底约 150 ms）。
   - 354 条三语集：Top-1 **96.89% → 96.61%**（-1 条，可通过对齐现有 `tier`/`addHit`/排序恢复到持平，见 §6）、Top-5 97.18% → 96.89%（-1 条）。
   - 30 条难例（28 条有解；tailuo/taidu 标注“当前不支持”）：**24/28 → 28/28**（typo、拼音、2 字片段、复方、盐型、品牌别名、零结果全过）。
4. **接入难度：中，约 1–1.5 人日**。改动集中在 `site/build.py` 的 `main()` 数据写出段（新增 1 个 pinyin.json + 读入 1 个 15.9 KB 汉字表）与内嵌 `APP_JS` 的 `loadIndex()` / `render()`（新增 ≈120 行，不改现有 `tier()`、`addHit()`、排序、国家视图、分页）；`?legacy=1` 与 P0/P1 懒加载行为完全不变。

---

## 1. 基准与方法

### 1.1 查询集

| 来源 | 条数 | 说明 |
|---|---:|---|
| `tests/trilingual/run_tests.py` CASES（AST 抽取，`extract_cases.py`） | **354** | 72 个案例 × en/es/zh；每案例有期望成分 `sid`；类别 single 51 / salt 17 / er 18 / combo 16 / dup_inn 15 / zh_only 13（按查询计） |
| `.tmp/search-bench/hard_cases.json`（新增） | **30** | typo 6（Lipit0r、atorvastatln…）、拼音 5（tainuo / liputuo / fenbide / tailuo / taidu）、2 字片段 5（地平/沙坦/洛尔/拉唑/头孢）、复方 3、盐型 4、中文/西语品牌 6、零结果 2 |
| 合计 | **384** | 全部查询的期望 sid 均在索引里（`unsolvable=0`） |

**判定**：Top-1 = 第一条命中的条目其成分集合（`v`/`vs`）含期望 sid；Top-5 同理放宽到前 5。难例按类型判定（sid 命中 / 名字含子串 / 复方 Top-5 任一成分 / 零结果必须空）。2 条无解拼音（tailuo/taidu，站点无拼音表）不计入分母 → 难例分母 **28**。

### 1.2 候选与配置

| 候选 | 配置 |
|---|---|
| **现状线性扫描**（baseline） | 复刻 `site/build.py` 内嵌 `app.js` 的 `norm/splitDose/tier/lev` 两遍扫描 + `addHit` 计分 + 排序（不含国家/剂量的次要加分项，固定常数；昵称 exact 路径保留） |
| **MiniSearch 7.2** | fields=`name(k+display+ingredients)`、`mah`；自定义 tokenizer（拉丁词 + CJK 单字/bigram）；`prefix:true`、`fuzzy: len>=5?0.2`、`boost{name:3,mah:.5}`；`toJSON` 序列化 |
| **FlexSearch 0.8** | `Document`，2 字段，`tokenize:'forward'`；预分词文本（CJK bigram 空格分隔）；`export/import` 序列化 |
| **Orama 3.1** | schema `{id,name,mah}`，自定义 tokenizer（空格切分，输入预分词）；`save()/load()` |
| **Fuse.js 7.5 混合** | exact 直映射 → 前缀二分，未命中才 `Fuse`（threshold .35）全量模糊；索引=全部 k 名数组 |
| **预构建倒排（自建）** | 令牌（拉丁词 + CJK bigram/整段）→ ids 倒排，idf 计分 + 拉丁前缀扩展，JSON 序列化 |
| **运行时派生 v3（推荐原型）** | 从内存 `IDX` 派生：exact Map / 前缀排序数组 / CJK bigram 倒排 / 拉丁 trigram+编辑距离 / 别名→成分；拼音用构建期小表。详见 §5 |

### 1.3 指标口径

- **首搜体积**：该方案首次搜索必须新增下载的索引/表（gzip -9）；所有方案都仍需 **P1 核心 3.84 MB** 用于渲染结果，故对比时以“新增字节”列。
- **构建/加载**：构建=把语料喂进库的耗时；加载=反序列化+可用耗时（现状=JSON.parse 34.8 MB）。
- **延迟**：查询函数纯匹配耗时（不含网络/渲染），热身 10 条后每条测 2 次；分数为 384 条汇总。

---

## 2. 结果总表

### 2.1 精度 / 体积 / 时间 / 延迟

| 候选 | Top-1 | Top-5 | 难例 Top-1 | **新增首搜字节（gzip）** | 构建 | 加载 | P50 | P90 | P99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 现状线性扫描（对照） | **96.89%** | **97.18%** | 24/28 | 0（核心 3.84 MB 已存在） | — | 311 ms（parse 34.8 MB） | **73.5 ms** | 104.8 ms | — |
| MiniSearch 7.2 | 93.22% | 96.89% | 24/28 | **5.68 MB** | 7.0 s | 3.4 s | 5.35 ms | 11.28 ms | 35.9 ms |
| FlexSearch 0.8 | 91.53% | 92.37% | 18/28 | **12.39 MB** | 3.8 s | 0.41 s | 0.013 ms | 0.22 ms | 5.1 ms |
| Orama 3.1 | 91.53% | 96.61% | 16/28 | **23.22 MB** | 4.1 s | 1.58 s | 0.152 ms | 2.65 ms | 47.5 ms |
| Fuse.js 7.5 混合 | 95.48% | 96.33% | 24/28 | **1.10 MB** | 0.36 s | 0（内存数组） | 0.004 ms | **238 ms**¹ | 1221 ms |
| 预构建倒排（JSON naive） | 95.76% | 96.89% | 18/28 | **4.02 MB** | 0.55 s | 37 ms | 0.003 ms | 0.148 ms | 15.2 ms |
| **运行时派生 v3（推荐）** | 96.61% | 96.89% | **28/28** | **0.39 MB**（拼音表；其余 0） | 0.68 s（可在 idle） | 0（从 IDX 派生） | **0.007 ms** | **0.073 ms** | **6.39 ms**（最坏 8.4 ms） |

¹ Fuse 混合的 P90 是“精确/前缀未命中 → 全量 Fuse 模糊”的尾延迟（126,915 名），与现状模糊兜底同量级；v2 原型用它时 P99 达 709 ms，因此 v3 换成 trigram+lev。

### 2.2 按语言 / 类别（Top-1%）

| 候选 | en | es | zh | single | salt | er | combo | dup_inn | zh_only |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 现状线性扫描 | 95.1 | 96.6 | **99.1** | 100 | 88.2 | 100 | 87.5 | 60 | 92.3 |
| MiniSearch | 95.9 | 94.8 | 88.7 | 95.3 | 94.1 | 100 | 93.8 | 46.7 | 92.3 |
| FlexSearch | 97.6 | 95.7 | 80.9 | 93.5 | 88.2 | 100 | 93.8 | 46.7 | 92.3 |
| Orama | 95.1 | 96.6 | 82.6 | 93.8 | 88.2 | 100 | 81.3 | 53.3 | 92.3 |
| Fuse 混合 | 95.9 | 95.7 | 94.8 | 98.5 | 82.4 | 100 | 93.8 | 60 | 84.6 |
| 预构建倒排 | 96.7 | 95.7 | 94.8 | 98.5 | 82.4 | 100 | 93.8 | 60 | 92.3 |
| **运行时派生 v3** | 95.1 | 95.7 | **99.1** | 100 | 82.4 | 100 | 87.5 | 60 | 92.3 |

> 结论：**中文（zh）是库的短板**——MiniSearch/FlexSearch/Orama 的 CJK tokenizer 在 354 条中文查询上掉 10–18 个百分点；自建派生与现状持平（99.1）。

### 2.3 难例逐项（推荐方案 28/28，现状 24/28）

| 类别 | 现状 | 推荐 v3 | 说明 |
|---|---|---|---|
| typo（Lipit0r / atorvastatln / metformln / ibuprofn / amlopidine / sertralina） | 5/6 | **6/6** | 现状只有 `tier` 的 Levenshtein ≤2/3，但排序把同分品牌名（famotidine 等）顶到前面；v3 trigram 短名单 + 距离优先排序修复 |
| 拼音（tainuo / liputuo / fenbide；tailuo、taidu 无解） | 0/3 | **3/3** | 0.39 MB 拼音表（token→sid），拼音命中直接列该成分全部条目 |
| 2 字片段（地平/沙坦/洛尔/拉唑/头孢） | 5/5 | **5/5** | CJK bigram 倒排 + 覆盖度排序 |
| 复方（氨氯地平阿托伐他汀等） | 2/3 | **3/3** | Top-5 任一成分命中 |
| 盐型（盐酸二甲双胍、苯磺酸氨氯地平…） | 3/4 | **4/4** | bigram 命中长盐型名 |
| 品牌别名（芬必得/扑热息痛/万艾可/代文/Gelocatil…） | 6/6 | **6/6** | 复用 `aliases.json` 的 exact 别名→成分路径（现状已有，派生层保留） |
| 零结果（xqzvbnm123 / 不存在的药名zzz） | 2/2 | **2/2** | trigram+距离阈值天然不命中；Fuse 全局模糊会漏（v2 曾返回 40 条噪声） |

---

## 3. 为什么库不划算（体积账）

所有方案都**不能替代** `data/idx/core.json`（3.84 MB gz）——结果表需要 `d/x/s/m/c/l/u/v/vs` 字段。因此：

```
现状 P1：核心 3.84 MB                    （首次搜索）
库方案 ：核心 3.84 + 库索引 1.10~23.22 MB = 4.94 ~ 27.06 MB   ← 全部比现状大
推荐方案：核心 3.84 + 拼音表 0.39（按需）  = 3.84 / 4.23 MB   ← 不劣于现状
legacy  ：6.08 MB（?legacy=1 不变）
```

- MiniSearch：`toJSON` 含全部 token 的 postings（20.8 MB raw），CJK bigram 让 token 数翻倍；加载 = `loadJSON` 重建内部结构 **3.4 s**（手机更慢）。
- FlexSearch：`export` 的 chunk 结构冗余（51 MB raw）；虽然查询极快（0.013 ms）但体积是现状 3 倍。
- Orama：`save()` 把文档存储+索引都序列化（114.9 MB raw），不可用于静态站。
- Fuse：唯一“体积可接受”（1.10 MB）的纯前端方案，但只索引名字、无字段加权；全量模糊兜底 P90 238 ms；且它只能做“名字相似”，拼音/2字片段仍需另写逻辑——最后仍会演变成自建派生索引 + Fuse 兜底（v2 原型已证明 P99 被拖到 709 ms）。

---

## 4. 为什么“运行时派生”成立

`site/build.py` 的 P1 已把 34.8 MB 索引压成 **15.26 MB raw / 3.84 MB gz** 的 `data/idx/core.json`，客户端 `decodeCore()`（当前 L1236）解回与 `index.json` 同构的 `IDX`。本方案直接在这份内存数据上派生匹配结构：

| 派生结构 | 构建耗时（Node 桌面） | 新增下载 | 用途 |
|---|---:|---:|---|
| exact Map（k→ids） + 前缀排序数组 | 204 ms | 0 | exact / prefix（384 条查询里 328 条走此路径，85%） |
| CJK bigram 倒排（14,603 个 bigram，来自 k） | 25 ms | 0 | `地平` 类 2 字片段 contains |
| 拉丁 trigram 倒排（13,333 个 trigram） | 454 ms | 0 | typo（trigram 短名单 + Levenshtein 精排） |
| 别名→成分（复用已下载 `aliases.json`） | ≈0 | 0 | 芬必得/扑热息痛/万艾可… |
| **拼音表 token→sid（构建期生成）** | 0（构建期） | **0.39 MB gz** | 拼音 tailuo…、中文名拼音 |

- **内存**（`--expose-gc` 实测）：`IDX` 常驻 85 MB；exact/prefix ≈0；CJK bigram +2.5 MB；trigram **+24.9 MB**（合计约 112 MB 堆）。移动端 trigram 是唯一内存风险，见 §7 缓解（懒构建 / 打平为 `Uint32Array` 预计 8–10 MB）。
- **构建时机**：exact/prefix 204 ms 可在 `loadIndex()` 完成后立即做；bigram 25 ms 随意；trigram 454 ms 放 `requestIdleCallback`（用户首查仍走原线性扫描，收到第一个结果后派生层就绪，下一次按键即走快路径）。

### 4.1 拼音表可以合法地“构建期生成”

- 拼音查询需要读音数据，浏览器端无法推导 → 必须随站点下发一张表。
- 方案：把 **1,582 个汉字 → 拼音** 的字符表（`pinyin_chars.json`，**15.9 KB raw / 7.45 KB gz**，由 pinyin-pro 一次性生成，MIT）放到 `data/sources/`（或作为构建常量）；`site/build.py`（只用 stdlib）读表，为 11,710 个含中文的 k + 422 条别名生成 `data/idx/pinyin.json`（token→sid）。
- 已用 Python stdlib 从字符表重建同一产物：**raw 1.38 MB / gzip 390,939 B（382 KB）**，与 Node 版（389,426 B）几乎一致；用字符表验证 `tainuo→acetaminophen`、`liputuo→atorvastatin`、`fenbide→ibuprofen` 均命中（`tailuo` 有 2 个成分、`taidu` 无命中，与难例设定一致）。
- 多音字风险：字符表取默认读音（去声调后多数可命中：得 dé→de）；对品牌名少见读音可能错，但拼音只是**新增兜底路径**，不影响 exact/prefix 结果；后续可在表里加例外覆盖。

---

## 5. 推荐方案（v3 架构）

```
首次输入 ──▶ loadIndex()（现状不变）
             ├─ fetch data/idx/core.json 3.84 MB → decodeCore → IDX（现状 L1265-1270）
             ├─ fetch aliases.json / confused.json（现状 L1275-1278）
             └─ 新增：派生 SearchLayers（内存，0 下载）
                  ├─ 立即：exactMap + sortedIds（204 ms）
                  ├─ idle：cjkBigram（25 ms）+ latinTrigram（454 ms）
                  └─ 拼音查询时按需：fetch data/idx/pinyin.json（0.39 MB gz，一次）
render()：把「第一遍扫描全部 IDX」改成「枚举 SearchLayers.match(nq) 给出的候选」
          - 候选→[[score,tier,entry]] 仍走现有 addHit()/排序/国家视图/分页，不改行为
          - FEATURE FLAG：SEARCH_LAYERS 为空或异常 → 走原有线性扫描（=现状）
          - ?legacy=1 → 完全不碰 layers（走 index.json 6.06 MB 老路径）
```

### 5.1 精度口径（为什么推荐做法能保住现状 Top-1）

- **只替换“候选枚举”，不替换打分/排序**：exact/prefix/alias/contains 候选仍交给现有 `tier()`+`addHit()`+sort，因此这些路径与现状逐条一致；新增的 pinyin/typo 候选使用显式 tier 标签（`pinyin` 0.9、`fuzzy` 0.55）参与同一排序。
- v3 原型是“独立排序”版本（Top-1 96.61 vs 现状 96.89，差 1 条 salt 案例）；按上述集成方式，expected Top-1 ≥ 96.89，且难例 24/28→28/28 的提升保留。
- 逐条回归门槛：354 三语集 + 30 难例 + 线上高频品牌名抽查 50 条，全部跑通才允许合入。

### 5.2 代码片段 A：`site/build.py` —— 构建期拼音表（标准库，插在 core.json 写出之后）

```python
# main() 内，约 L2700-2712 之间（core.json 已写、aliases 已 build）
PINYIN_CHARS = json.loads((ROOT / "data" / "sources" / "pinyin_chars.json").read_text("utf-8"))

def pinyin_tokens(text: str) -> set[str]:
    """汉字→拼音（去声调）；拉丁片段原样。返回 s:/j:/i: 三类 token。"""
    toks, syl = set(), []
    for ch in text or "":
        if "\u3400" <= ch <= "\u9fff":
            p = PINYIN_CHARS.get(ch)
            if p: syl.append(p); toks.add("s:" + p)
        elif ch.isascii() and ch.isalnum():
            syl.append(ch.lower()); toks.add("s:" + ch.lower())
    if len(syl) > 1:
        toks.add("j:" + "".join(syl)); toks.add("i:" + "".join(x[0] for x in syl))
    return toks

# 名字键（含中文的 k）→ 拼音 token → 主成分 sid
py: dict[str, list[str]] = {}
for e in entries:
    if not re.search(r"[\u3400-\u9fff]", e["k"]):
        continue
    for tk in pinyin_tokens(e["k"]):
        py.setdefault(tk, [])
        if e["v"] not in py[tk]: py[tk].append(e["v"])
# 别名（俗称）拼音 → 成分 sid：让「fenbide / tainuo」也能命中
for a in aliases:
    label = a.get("a") or a.get("n") or ""
    if not a.get("v") or not re.search(r"[\u3400-\u9fff]", label):
        continue
    for tk in pinyin_tokens(label):
        py.setdefault(tk, [])
        if a["v"] not in py[tk]: py[tk].append(a["v"])

(OUT / "data" / "idx" / "pinyin.json").write_bytes(json.dumps(
    {"v": 1, "tokens": [[k, v] for k, v in py.items()]},
    ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
# 注意：pinyin_chars.json（15.9 KB）需一次性加入 data/sources/ 并注明来源/许可（pinyin-pro，MIT）
```

> app.js 版本号替换链（当前 L2664-2668）加一行：`.replace("data/idx/pinyin.json", f"data/idx/pinyin.json?v={int(time.time())}")`。

### 5.3 代码片段 B：`site/build.py` 内嵌 `APP_JS` —— 派生层 + 候选枚举

```js
// ① 全局（约 L638 附近，IDX 声明之后）
let SEARCH_LAYERS = null;   // { exact, sorted, bigram, trigram, py, pyMap, ready }

// ② 派生（loadIndex() 的 then 里，IDX=d 之后）
function buildSearchLayers(){
  try{
    const exact = new Map(), sorted = new Array(IDX.length);
    for(let i=0;i<IDX.length;i++){
      const k = IDX[i].k;
      if(!exact.has(k)) exact.set(k, []);
      exact.get(k).push(i);
      sorted[i] = i;
    }
    sorted.sort((a,b)=> IDX[a].k < IDX[b].k ? -1 : IDX[a].k > IDX[b].k ? 1 : 0);
    const bigram = new Map(), trigram = new Map();
    const addTo = (m,k,id)=>{ let a=m.get(k); if(!a){a=[];m.set(k,a);} a.push(id); };
    const cjkBigrams = (s)=>{ const o=[]; for(const r of String(s).match(/[\u3400-\u9fff]+/g)||[]){ if(r.length===1)o.push(r); for(let j=0;j+1<r.length;j++)o.push(r.slice(j,j+2)); } return o; };
    const trigrams = (s)=>{ const t=' '+s.replace(/\s+/g,' ')+' '; const o=[]; for(let i=0;i+3<=t.length;i++)o.push(t.slice(i,i+3)); return o; };
    for(let i=0;i<IDX.length;i++){
      const k = IDX[i].k;
      if(/[\u3400-\u9fff]/.test(k)) for(const bg of new Set(cjkBigrams(k))) addTo(bigram,bg,i);
      if(/^[a-z0-9 ]+$/.test(k) && k.length>=4) for(const tg of new Set(trigrams(k))) addTo(trigram,tg,i);
    }
    SEARCH_LAYERS = { exact, sorted, bigram, trigram, py: null, ready: true };
  }catch(e){ SEARCH_LAYERS = null; if(window.console) console.warn('search layers failed', e); }
}
// ③ 候选枚举（只读层；命中类型用于给 tier 标签）
function layerCandidates(nq){
  const L = SEARCH_LAYERS; if(!L) return null;
  const out = new Map();  // id -> tier 名
  const ex = L.exact.get(nq);
  if(ex){ ex.forEach(id=>out.set(id,'exact')); return out; }
  // prefix：排序数组二分
  let lo=0, hi=L.sorted.length;
  while(lo<hi){ const m=(lo+hi)>>1; if(IDX[L.sorted[m]].k < nq) lo=m+1; else hi=m; }
  for(let i=lo;i<L.sorted.length && out.size<200 && IDX[L.sorted[i]].k.startsWith(nq);i++) out.set(L.sorted[i],'prefix');
  if(out.size) return out;
  // CJK 2 字片段：bigram 交集（≥2 命中才收，避免噪音）
  const grams=[...new Set(nq.match(/[\u3400-\u9fff]+/g)||[])].flatMap(r=>{...});
  const cnt=new Map();
  for(const g of grams){ const ids=L.bigram.get(g); if(ids) for(const id of ids) cnt.set(id,(cnt.get(id)||0)+1); }
  [...cnt.entries()].filter(([,c])=>c>=Math.min(2,grams.length)).sort((a,b)=>b[1]-a[1]).slice(0,200).forEach(([id])=>out.set(id,'contains'));
  if(out.size) return out;
  // 拼音（懒加载表；见 ④）
  if(L.py){ ...同原型 C5，命中 out.set(id,'pinyin')... if(out.size) return out; }
  // 拉丁 typo：trigram 短名单 + lev
  ...top-300 短名单里 lev(nq,k)<=阈值 → out.set(id,'fuzzy')...
  return out;   // 可能为空 → render 显示“无匹配”
}

// ④ 拼音表按需加载（仿现有 artgFallback 的懒加载写法）
let PY_P = null;
function ensurePinyin(){
  if(!SEARCH_LAYERS || SEARCH_LAYERS.py) return Promise.resolve(true);
  if(PY_P) return PY_P;
  PY_P = fetch(BASE + 'data/idx/pinyin.json?v=' + VERSION)
    .then(r=>r.json()).then(d=>{ SEARCH_LAYERS.py = new Map(d.tokens); return true; })
    .catch(()=>{ PY_P = null; return false; });
  return PY_P;
}

// ⑤ render() 改造（当前 L983-1003 的两遍 for(const e of IDX)）
const cand = IDX_READY && !LEGACY ? layerCandidates(nq) : null;
if(cand){
  for(const [id, kind] of cand){
    const e = IDX[id];
    const t = kind==='pinyin' ? ['pinyin', 0.90] : kind==='fuzzy' ? ['fuzzy', 0.55] : tier(nq, e.k);
    if(t) addHit(e, t);
  }
  // 拼音都没命中、且 nq 是纯拉丁 ≥3 字 → 后台加载拼音表后重跑一次
  if(!hits.length && /^[a-z]+$/.test(nq) && nq.length>=3) ensurePinyin().then(ok=>{ if(ok) render(); });
}else{
  for(const e of IDX){ ...原两遍扫描，一行不改... }   // 回退/legacy 路径
}
```

> 接入点行号（sha256 `6f76cd5d…` 快照）：`IDX` 声明 L638；`tier()` L698；`render()` L951；第一遍扫描 L983–993；模糊第二遍 L994–1003；`LEGACY` L1207；`decodeCore()` L1236；`loadIndex()` L1272；`loadIndex` 的 then（挂 `buildSearchLayers()`）L1279–1285；`box` focus 懒加载 L1386；build.py 数据写出段 L2694–2712；APP_JS 版本替换链 L2664–2668。

---

## 6. 前后指标汇总

| 指标 | 现状（P1 懒加载 + 线性扫描） | 推荐 v3 | 变化 |
|---|---|---|---|
| 首搜下载（P0/P1 路径） | 3.86 MB（core 3.84 + aliases） | **3.86 MB**（不变） | 0 |
| 拼音查询额外下载 | —（不支持） | +0.39 MB（首次拼音查询，之后缓存） | 新增能力 |
| legacy `?legacy=1` | 6.08 MB | 6.08 MB（不变） | 0 |
| 每次按键匹配（桌面 Node） | P50 73.5 ms / P90 104.8 ms | **P50 0.007 ms / P90 0.073 ms / P99 6.4 ms** | ≈10,000×（P50） |
| 模糊/typo 兜底 | 第二遍全表 ≈ 74–100 ms | trigram+lev ≈ 1–8 ms | ≈10× |
| 354 条 Top-1 / Top-5 | 96.89% / 97.18% | 96.61% / 96.89%（独立排序原型；按 §5.1 集成应 ≥ 现状） | ≈持平 |
| 30 难例（28 有解） | 24/28 | **28/28** | +4 |
| 中文（zh）Top-1 | 99.1% | 99.1% | 持平 |
| 一次性派生构建 | — | 683 ms（可 idle；首查仍立即可用） | 新增 |
| JS 堆增量 | — | +2.5 MB（bigram）+24.9 MB（trigram） | 见 §7 |
| `site/dist` 新增 | — | `pinyin.json` raw 1.38 MB（gzip 0.39 MB）+ 1 个文件 | publish.ps1 检查不受影响 |

---

## 7. 风险与回退

| 风险 | 说明 | 缓解 / 回退 |
|---|---|---|
| 排序回归（Top-1 掉点） | 原型独立排序比现状 -1 条 | **只替换候选枚举、保留现有 `tier/addHit/sort`**；354+30 条回归门禁；`?enh=0`/`?legacy=1` 双开关 |
| 派生构建阻塞 | 683 ms 一次性（手机 1.5–2 s） | exact/prefix 204 ms 立即；bigram+trigram 放 `requestIdleCallback`；首查仍走线性扫描 |
| 移动端内存 | trigram +24.9 MB（IDX 本身 85 MB） | trigram 懒构建（首次 typo 查询时）；打平成 `Uint32Array` 预计 8–10 MB；低端机可通过 `navigator.deviceMemory` 跳过 |
| 拼音多音字 / 覆盖不足 | 字符表默认读音 | 拼音只做增量路径，不影响 exact；表可加例外覆盖；无表时静默跳过 |
| `pinyin_chars.json` 许可/来源 | 需随仓库提交 15.9 KB 汉字表 | 由 pinyin-pro（MIT）一次性生成，注明来源与生成脚本；提交前需人确认数据来源（pinyin 数据本身为事实映射） |
| 与并行任务冲突 | `site/build.py` 正被其他任务修改（一天内 sha 已变 3 次） | 动工前 `Select-String` 重新定位函数；只加不删；与当前 P0/P1/P2 任务协调同一文件写入 |
| 索引缓存 | 新增 pinyin.json 需要版本参数 | 沿用 `?v=<build ts>`（与 core.json 同机制） |
| 与 `lib/search.py` 行为分叉 | 服务端/CLI 仍是 Python 检索层 | 本次仅客户端增强；354 条集本身是两边共享回归基线，未来 Python 侧如需拼音可复用同一 `pinyin.json` |
| 回滚 | 前端 + 新数据文件 | 删除 `pinyin.json` + 前端 layers 代码在 `try/catch` 内：任何异常自动回退线性扫描；发布回滚按 §6/DEPLOY 走 `publish.ps1` |

---

## 8. 验收清单

```powershell
$node = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$py   = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$pnpm = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\pnpm\bin\pnpm.mjs'

# 0) 依赖只装在 .tmp/search-bench（首次或清理后需重装；不影响仓库）
& $node $pnpm --dir .tmp/search-bench add minisearch flexsearch "@orama/orama" fuse.js pinyin-pro

# 1) 本基准复跑（数据只读）
& $node .tmp\search-bench\bench.mjs          # 6 方案总表 → results.json
& $node .tmp\search-bench\hard_detail.mjs    # 公平基线 + 难例明细 → hard_detail.json
& $node .tmp\search-bench\derived3.mjs       # 推荐原型（含拼音表构建） → derived3_results.json
& $py   .tmp\search-bench\pinyin_charcheck.py# 字符表→拼音产物一致性 → 控制台

# 2) 合入前回归门槛（接入后）
#    - tests/trilingual/run_tests.py 354 条（Python 侧不变，仍全过）
#    - 同一 354 + 30 难例走浏览器端：Top-1 不低于 96.89，难例 ≥28/28
#    - 首搜字节：DevTools 网络面板确认首次输入仅 core+aliases（3.86 MB），拼音查询 +0.39 MB
#    - ?legacy=1：首搜 6.06 MB、行为与旧版一致
#    - 移动端（360px，CPU 4× throttle）：输入到结果 < 100 ms（不含网络），无长任务 > 50 ms 卡顿
```

---

## 9. 附录：文件与复现

| 路径 | 内容 |
|---|---|
| `.tmp/search-bench/extract_cases.py` → `cases.json` | 从 `tests/trilingual/run_tests.py` AST 抽取 354 条查询（72 案例，含期望 sid/类别/语言） |
| `.tmp/search-bench/hard_cases.json` | 30 条难例（typo/拼音/2 字片段/复方/盐型/品牌/零结果） |
| `.tmp/search-bench/bench.mjs` → `results.json` | 6 方案统一基准（Top-1/Top-5/难例/体积/构建/加载/P50-P90） |
| `.tmp/search-bench/hard_detail.mjs` → `hard_detail.json` | 公平基线（修正 aliases 预过滤）+ 难例逐条明细 |
| `.tmp/search-bench/derived3.mjs` → `derived3_results.json` | **推荐方案原型 v3**（运行时派生 + 拼音表；28/28 难例） |
| `.tmp/search-bench/derived2.mjs` / `derived.mjs` | v2（Fuse 兜底，P99 709 ms）/ v1 迭代记录 |
| `.tmp/search-bench/pinyin_size.mjs` / `char_table.mjs` / `pinyin_chars.json` | 拼音表体积（字符表 1,582 字 / 15.9 KB raw / 7.45 KB gz）与产物（1.38 MB raw / 390 KB gz） |
| `.tmp/search-bench/memory2.mjs` | 派生层堆内存（IDX 85 MB；bigram +2.5 MB；trigram +24.9 MB） |
| `.tmp/search-bench/pinyin_charcheck.py` | Python stdlib 用字符表重建拼音产物的验证（tainuo/liputuo/fenbide 命中） |
| `.tmp/search-bench/probe*.mjs` | 库 API 探测（FlexSearch export/import、Orama save/load、MiniSearch loadJSON） |

**限制与说明**
- 延迟为 Node 桌面基准；移动端按 3–5× 估计（P50 仍在亚毫秒级，主要成本是网络与首次派生构建）。
- 基线为 `app.js` 算法的忠实复刻（含 `norm/splitDose/tier/lev/addHit/排序`），未包含当前版本新增的 `parseQuery`/国家视图/分页渲染耗时；后者不属于匹配层，接入时保持不变。
- 库索引体积按各自官方序列化接口实测（MiniSearch `toJSON` / FlexSearch `export` / Orama `save`），未做二次压缩（Pages 会再 gzip，已按 gzip-9 比较）。
- 未对线上站点做任何请求/发布；所有数据来自工作区快照。
