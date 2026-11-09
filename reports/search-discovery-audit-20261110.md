# 搜索与类别发现 · 可行性审计（v0.10.1 快照 · 2026-11-10）

> **性质**：只读审计。没有改代码、没有改 `data/drugs.db`、没有跑 `site/build.py`、没有碰 `site/dist`、没有 commit / 发布。
> 临时脚本全部在 `.tmp/audit/`（`server.py` / `bench.html` / `bench2.html` / `probe_rank.py` / `rank_variants.py` / `rank_h.py` / `size_probe.py` / `size_atc_slices.py` / `alias_diff.py` / `gen_tables.py` / `gen_proto.py`，均可复跑）。
> **快照**：git `e814a74f6`（v0.10.1），`site/dist` = v0.10.1 构建产物（`data/idx/core.json` 41,492,440 B）。
> **环境**：本机没有 node（`node -v` → 命令未找到），所以客户端耗时不用 node 估，改用本机 **Chrome 156.0.8078.81 headless**（`--headless=new --dump-dom` + 同步 XHR）实测 V8；Python 3.12.14（`$py`）。
> **口径**：`raw` = 文件字节，`gz` = 本机 `gzip.compress(data, 6)`（与 `deploy/verify_live.py:123` 的 gzip -9 略有差别，仅比较量级）。所有数字都是本次现查，没有照抄历史报告。
> **底线**：本文只讨论身份对应与「不可互换」警示的实现方式，不给用药建议、不做剂量换算、不判断可替代（AGENTS §1/§9）。商品名仍然不是主键——大类/ATC 结果依旧是候选集（`renderCategory` / `renderATC` 的表头写明「候选/不排序推荐」），本批不引入「唯一答案」。

---

## 0. 结论先行

| # | 问题 | 根因（文件:行） | 补丁 | 难度 | 构建增量 | 进 v0.10.2 |
|---|---|---|---|---|---|---|
| 1 | ATC / 大类**首查 2.7 s（localhost）/ 12.7 s（8 Mbps）**，等于把所有 195,553 条索引拉一遍 | 首查必须等 `data/idx/core.json`（41.49 MB raw / **9.89 MB gzip**）+ `decodeCore` 走完（`site/build.py:5012-5021`、`5089-5122`、`5123-5159`、`4578-4614`、`4510-4556`）；`categories.json` 只是 299 KB 的零头 | 构建期预生成 `data/idx/cats.json`（22.9 KB raw / 7.0 KB gz）+ 每类 top200 切片（16 个文件 0.65 MB raw / 0.11 MB gz）+ `atc-ing.json`（62 KB raw / 25 KB gz）；首查只 fetch 小文件，core 转后台补全 | **中** | **+0.74 MB raw / +0.14 MB gz** | **值得**（单独一个提交，带 fallback） |
| 2 | 「退烧药」在站点 **0 结果**；lib 有 66 条口语词，客户端 `categories.json` 只有 4 语 label + id | lib 的口语词表只活在 `lib/categories.py:121-153`，`site/build.py:9686-9708` 生成 `categories.json` 时**完全没读它**，客户端 `catHit()`（`site/build.py:4563-4577`）自然认不出 | 把词表搬到唯一来源，`build_categories_json()` 把口语词并进各类的 `aliases`（老客户端也立刻生效），`cats.json` 同源生成；lib 改为 import 同一份表 | **小** | `cats.json` 内已含；`categories.json` +≈1 KB raw | **值得** |
| 3 | 24 条大类期望 **3 条未进 Top5**（21/24 = 87.5%），CI 门槛 ≥95% 红 | `lib/search.py:771` 按**单张卡**的 `n_products` 排序；一张卡 = key×国家×成分组合×剂型，成分被拆散。组合感冒药一张卡 713 条把「抗过敏药」的单成分挤出前 5 | 只改排序键：先按「成分在本类别内的 active 产品总数」排，再按卡片 `n_products` 排（成分聚合 = 组内去重，不改数据） | **小** | 0 | **值得** |

一句话：**三个都能做，都不碰数据层**。#2 / #3 是一个低风险提交；#1 收益最大（12.7 s → 0.06 s 量级）但要重写首查路径，单独提交并保留今天的 `core.json` 回退。

---

## 1. 方法与复现

### 1.1 客户端耗时怎么量的（没有 node）

`app.js` 就是 `site/build.py:3310` 起的 `APP_JS` 常量，`site/build.py:10482-10488` 写进 `dist/assets/app.js`。为了量「首查要多久」，我做了三件只读的事：

1. `.tmp/audit/server.py`：把 `site/dist` 当静态目录，`.json` 用 **gzip** 发送（模拟 GitHub Pages 的动态压缩），`--kbps` 参数按 32 KB 一块限速（模拟 8 / 16 Mbps）。
2. `.tmp/audit/bench.html`：**逐行复制** `build.py:4985-5008` 的 `decodeCore()`、`build.py:4591-4597` 的 `renderCategory` 过滤、`build.py:4533-4538` 的 `renderATC` 过滤、`build.py:4559-4577` 的 `_catNorm/catHit`，用同步 XHR 保证测量结束才触发 `load`。
3. `chrome --headless=new --dump-dom http://127.0.0.1:<port>/bench`，从 `<pre>` 里取 JSON。

```powershell
# 复现（三档：localhost / 16 Mbps / 8 Mbps）
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
Start-Process $py -ArgumentList '.tmp/audit/server.py','--port','8770'
Start-Process $py -ArgumentList '.tmp/audit/server.py','--port','8771','--kbps','8000'
& 'C:\Program Files\Google\Chrome\Application\chrome.exe' --headless=new --disable-gpu `
  --user-data-dir=.tmp/audit/chrome1 --dump-dom http://127.0.0.1:8770/bench
```

### 1.2 数据面

- `& $py -c "..."` 直接读 `site/dist/data/idx/core.json` / `categories.json`（只读文件）；
- `& $py db/q.py` / `sqlite3.connect('file:data/drugs.db?mode=ro', uri=True)` 现查 DB；
- 评测：`& $py tests/search_eval/run_ci.py --category category --json .tmp/audit/ci_cat.json`（只读开库，脚本本身 `run_ci.py:55-62` 强制 `mode=ro`）。

---

## 2. 问题 1：ATC / 大类索引首次查询慢

### 2.1 现状证据（现查）

**首查要解析的数据量**

| 资源 | raw | gzip | 记录数 | 说明 |
|---|---:|---:|---:|---|
| `data/idx/core.json` | **41,492,440 B** | **9.89 MB** | **195,553 条 × 25 列** | `manifest.json:3` 的 `n=195553`；20 列是字典编码（`c:367 / x:27,722 / atc:10,474 / s:32,511 / v:9,666 / vs:15,203 / cu:6,747 / db:51 …`） |
| `data/aliases.json` | 892,886 B | 0.09 MB | 1,144 条 | `loadSupport()`（`build.py:5031-5040`）无条件拉 |
| `data/categories.json` | 299,356 B | 0.05 MB | 1,170 条（16 大类 + **1,154 个 ATC 码**） | 同上；`atc_codes` 1,154 |
| `data/idx/manifest.json` | 31,316 B | 0.01 MB | 163 片 | `loadShardedIndex()` 先拉它 |
| 该查询命中的分片（例：`降压药` → `cjk-j` 1 片） | 528,064 B | 0.10 MB | 2,101 条 | `shardsForQuery()` 取 1–3 片（`build.py:5049-5057`） |
| **大类词首查合计（例：降压药）** | **≈43.2 MB** | **≈10.1 MB gz** | 195,553 + 1,144 + 1,170 | 真正决定耗时的是 core.json（96%） |

`退烧药` 更糟：`退` 不在 `manifest.cjkInitials` 里（现查 `ci.get('退') → None`），`shardsForQuery()` 返回 `null` → `loadShardedIndex()` 抛 `no shard for query`（`build.py:5077-5084`）→ 直接掉进 `loadIndex()` 全量拉 core，最后 `catHit()` 返回 `null`，**花了 10 s 以上得到 0 结果**。

**客户端实测（冷启动、无缓存、desktop Chrome，单位 ms）**

| 阶段 | localhost | 16 Mbps | 8 Mbps |
|---|---:|---:|---:|
| fetch `core.json`（gzip 9.89 MB，浏览器解压后 `responseText` 39.16 M 字符） | 1,619 | 6,623 | 11,540 |
| `JSON.parse` | 143 | 125 | 126 |
| `decodeCore`（195,553 × 26 次属性写入） | **868** | 851 | 855 |
| 大类前缀过滤 + 按 n 排序（命中 7,519 条） | 106 | 114 | 113 |
| 单 ATC 码过滤（`C07`，命中 1,179 条） | 16 | 18 | 17 |
| `categories.json` fetch + parse | 10.6 | 28.1 | 44.2 |
| **首查 ATC（`C07`）总计** | **2,753** | **7,731** | **12,651** |
| **首查大类（`Blood-pressure medicines`）总计** | **2,763** | **7,759** | **12,695** |

> 复现：`.tmp/audit/bench.html` 输出 `BENCH={"t_fetch_ms":…,"t_decode_ms":…,"t_first_atc_ms":…}`。
> 结论：**用户说的「约 10 s」= 8–12 Mbps 的 4G 档**（9.89 MB gzip ≈ 8–10 s），与本次 8 Mbps 实测 12.65 s 同量级；desktop 即便 localhost 也要 2.75 s，其中 **decodeCore 占 0.87 s**（手机 V8 大约再慢 2–4 倍）。

### 2.2 根因（文件:行）

1. **首查路径把「类别识别」和「全量索引」绑在一起**：
   - `render()` `build.py:4631` 先判 ATC 码，`build.py:4636` 再判大类词；
   - `renderCategory()` `build.py:4586-4590`：`if(!IDX_READY){ … loadIndex()… }` —— 没 core 就不渲染；
   - `renderATC()` `build.py:4527-4532`：同上；
   - `startSearch()` `build.py:5144`：`if(atcQuery(...)){ loadIndex()… }` —— ATC 码连分片都不走，直接全量；
   - `loadIndex()` `build.py:5089-5122` → `loadMainIndex()` `build.py:5012-5021` → `decodeCore()` `build.py:4985-5008`。
2. **类别词表也搭在同一个大包上**：`loadSupport()` `build.py:5031-5040` 把 `aliases.json`+`confused.json`+`categories.json` 打包成 `SUPPORT_P`，只有 `loadIndex()`/`loadShardedIndex()` 才触发 → 认识一个类别词的最小代价是 1.2 MB，认完还得再等 41 MB。
3. **过滤是 O(N) 全表扫**：`build.py:4591-4596`（大类）与 `4533-4538`（ATC）都遍历整个 `IDX`。扫本身只要 100 ms（不是瓶颈），但它把「必须先有 core」这个约束钉死了。

### 2.3 方案：构建期预生成紧凑类别索引

**文件布局（新增 3 类产物，全部由 `site/build.py` 生成）**

```
site/dist/data/idx/cats.json          词表 + 16 类元数据 + ATC4 码 + 成分总量（22.9 KB raw / 7.0 KB gz）
site/dist/data/idx/cat-<id>.json      每类 top200 结果切片（16 个，30–57 KB raw；4–13 KB gz/个）
site/dist/data/idx/atc-ing.json       ATC L1–L4 码 → 成分（526 码，62 KB raw / 25 KB gz）
```

`cats.json` 结构（**实测原型 22,881 B raw / 7,022 B gz**，含 16 类的 ATC4 码与 1,154 个 `atc_codes`；生成脚本 `.tmp/audit/gen_proto.py`）：

```jsonc
{
  "v": "<BUILD_V>",
  "words": {"退烧药": "cat:analgesics", "c07": "atc:C07", "bloodpressuremedicines": "cat:antihypertensives", …},
  "cats": [{
    "id": "analgesics", "url": "cat/analgesics.html",
    "prefixes": ["N02", "M01A"],
    "labels": {"en": "…", "es": "…", "zh": "…", "zh-Hant": "…"},
    "atc4": ["N02B", "M01A", "N02A", "N02C"],
    "ing": [["Acetaminophen", 10002], ["Ibuprofen", 3216], …],   // 排序 + 首屏成分预览用
    "slice": {"f": "data/idx/cat-analgesics.json", "n": 200}
  }],
  "atc_codes": ["C07", …]      // 1,154 个，替代现在 categories.json 里的 atc_codes（≈9 KB）
}
```

**生成位置**：新增 `build_cat_word_index(db, entries)`，紧挨 `build_categories_json()`（现 `build.py:9686-9708`）放，`main()` 里在 `build_categories_json(db)`（现 `build.py:10661`）之后调用；`entries` 已经在 `build.py:10545` 拿到（`load_index(db)`），不必二次查库。

```python
# site/build.py —— 新增（放在 build_categories_json() 之后）
CAT_IDX_REL = "data/idx/cats.json"

def _cat_norm(s: str) -> str:                       # 与客户端 _catNorm 同口径（build.py:4559-4562）
    import unicodedata as _u
    t = _u.normalize("NFKD", str(s or ""))
    t = "".join(ch for ch in t if not _u.combining(ch))
    return re.sub(r"\s+", "", t).lower()

def _ing_totals(db, prefixes):                      # 成分在本类别的 active 产品数（与 §4 同一口径）
    cond = " OR ".join("s.atc LIKE ?" for _ in prefixes)
    rows = db.execute(
        f"""SELECT s.inn_en AS inn, COUNT(DISTINCT p.product_id) AS n
            FROM substance s JOIN variant v ON v.substance_id = s.substance_id
            JOIN product_component pc ON pc.variant_id = v.variant_id
            JOIN product p ON p.product_id = pc.product_id AND p.status = 'active'
            WHERE s.atc IS NOT NULL AND ({cond})
            GROUP BY s.substance_id""", tuple(p + "%" for p in prefixes)).fetchall()
    return rows

def _atc4_of(db, prefixes) -> list[str]:
    """该大类实际覆盖到的 ATC 4 位码（现查，不用手工表）。"""
    cond = " OR ".join("s.atc LIKE ?" for _ in prefixes)
    return sorted({r[0][:4] for r in db.execute(
        f"SELECT DISTINCT s.atc FROM substance s WHERE s.atc IS NOT NULL AND ({cond})",
        tuple(p + "%" for p in prefixes)) if r[0]})

def build_cat_word_index(db: sqlite3.Connection, entries: list[dict]) -> dict[str, int]:
    """把「类别词 → 大类/ATC」+ 每类 top200 切片预生成到 data/idx/。

    派生自 CONSUMER_CATEGORIES + COLLOQUIAL_ALIASES + entries，不引入任何人工标注；
    商品名仍只是候选集（切片里同样是候选条目，页面文案不变）。
    """
    idx_dir = OUT / "data" / "idx"
    words: dict[str, str] = {}
    cats: list[dict] = []
    for cat in CONSUMER_CATEGORIES:
        for label in cat["labels"].values():
            if label:
                words[_cat_norm(label)] = "cat:" + cat["id"]
        words[_cat_norm(cat["id"])] = "cat:" + cat["id"]
        totals = {r["inn"]: r["n"] for r in _ing_totals(db, cat["prefixes"])}
        hit = [e for e in entries
               if e.get("atc") and any(str(c).startswith(p) for c in e["atc"] for p in cat["prefixes"])]
        hit.sort(key=lambda e: (-max((totals.get(s, 0) for s in (e.get("x") or "").split(" + ")), default=0),
                                -(e.get("n") or 0)))
        top = hit[:200]
        name = f"cat-{cat['id']}.json"
        (idx_dir / name).write_bytes(json.dumps(top, ensure_ascii=False,
                                                separators=(",", ":")).encode("utf-8"))
        cats.append({"id": cat["id"], "url": f'cat/{cat["id"]}.html',
                     "prefixes": list(cat["prefixes"]), "labels": dict(cat["labels"]),
                     "atc4": _atc4_of(db, cat["prefixes"]),          # 4 位码列表，见下
                     "ing": [[r["inn"], r["n"]] for r in _ing_totals(db, cat["prefixes"])[:16]],
                     "slice": {"f": "data/idx/" + name, "n": len(top)}})
    for word, cat_id in COLLOQUIAL_ALIASES.items():      # §3 的同步：一处词表，两处产物
        words[_cat_norm(word)] = "cat:" + cat_id
    payload = {"v": BUILD_V, "words": words, "cats": cats,
               "atc_codes": sorted(_all_atc_codes(db))}
    (idx_dir / "cats.json").write_bytes(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return {"words": len(words), "cats": len(cats), "bytes": (idx_dir / "cats.json").stat().st_size}
```

> `_all_atc_codes(db)` 直接复用 `build_categories_json()` 现在已经算好的 `_atc_groups(db)`（L1/3/4/5 共 1,154 个），不要另写一遍。

**客户端加载点（`APP_JS`）**：不要动 `loadSupport()` 的语义，另开一条轻量链：

```js
// build.py APP_JS —— 新增（放在 loadSupport 之后，约 5040 行附近）
let CATX = null, CATX_P = null;
function loadCatx(){
  if(CATX) return Promise.resolve(CATX);
  if(CATX_P) return CATX_P;
  CATX_P = fetchJSON(BASE + 'data/idx/cats.json')
    .then(x => { CATX = x || null; return CATX; })
    .catch(() => { CATX = null; CATX_P = null; return null; });   // 失败=回退老路径，不弹错
  return CATX_P;
}

// startSearch()（build.py:5123-5159）开头加一条：类别词 / ATC 码先走轻量索引
function startFastLane(q){
  const nq = norm(splitDose(q)[0]);
  return loadCatx().then(cx => {
    if(!cx || !cx.words) return false;
    const hit = cx.words[_catNorm(nq)] || cx.words[_catNorm(q)];
    if(!hit) return false;
    if(hit.indexOf('cat:') === 0) renderCategoryFast(cx, hit.slice(4), q);
    else renderATCFast(cx, hit.slice(4), q);
    return true;
  });
}
```

`renderCategoryFast()` 与今天的 `renderCategory()`（`build.py:4578-4614`）输出同构：解析条 + `atc.view_class` 链接 + `cat.disclaimer` + 分组表，只是数据源换成切片：

```js
function renderCategoryFast(cx, id, q){
  const cat = (cx.cats || []).find(c => c.id === id);
  if(!cat) return false;
  fetchJSON(BASE + cat.slice.f).then(rows => {
    const display = rows.map(e => [1, 'category', e]);      // 与 renderCategory 的 [score,tier,entry] 同构
    RES_GROUPS = groupByIngredient(display); LAST_DISPLAY = display;
    RES_LIMIT = RES_PAGE; RES_EXPANDED = new Set(); RES_MODE = 'grouped';
    out.innerHTML = bar + notice + link + `<div id="reswrap">${resultsTableHTML(T)}</div>`;
    meta.textContent = `${rows.length} ${T('res.matched')} · ${T('parse.category')} ${label}`;
    loadIndex(true);                                        // 后台补全（国家视图/同成分/分页）
  }).catch(() => loadIndex().then(ok => { if(ok) render(); }));   // 切片坏了 → 老路径
  return true;
}
```

ATC 码同理：`atc-ing.json` 先渲染「成分 + 产品数 + 类目页链接」，`loadIndex(true)` 后台补商品名行（`build.py:4527-4532` 已有「core 到位后重跑」的机制，不用新写）。

### 2.4 体积与收益（现查原型实测）

| 产物 | raw | gzip | 说明 |
|---|---:|---:|---|
| `cats.json`（16 类 + 66 口语词 + 成分 top16 + ATC4 码 + 1,154 个 `atc_codes`） | 22,881 B | 7,022 B | `.tmp/audit/gen_proto.py` 实测 |
| `cat-<id>.json` × 16（top200，trim 字段 `k,d,u,c,x,s,f,n,atc,v,vs`） | 654,501 B 合计 | ≈109 KB 合计 | 单类 30.3–56.7 KB raw（4.2–13.0 KB gz） |
| `atc-ing.json`（L1–L4 526 码 → 成分，实测全表 2,890 码是 155 KB raw / 57 KB gz） | 62,213 B | 25 KB | 只给 ATC 码查询用 |
| **合计** | **0.74 MB** | **0.14 MB** | dist 880 MB，可忽略 |

**首查耗时（同一台机器、同一个 8 Mbps 限速，`退烧药`）**

| 路径 | localhost | 8 Mbps | 传输字节 |
|---|---:|---:|---:|
| 今天（大类词，等价于 `降压药` 那条路径） | 2,763 ms | 12,695 ms | 43.2 MB raw / 10.1 MB gz |
| 预生成切片（`.tmp/audit/bench2.html` 实测 `退烧药`） | **5.9 ms** | **34.3 ms** | 22.9 KB + 43.0 KB = 65.9 KB raw / ≈12 KB gz |
| 倍数 | ≈470× | ≈370× | ≈650× raw / ≈840× gz |

> 原型目录：`.tmp/audit/proto/`（`gen_proto.py` 生成）；`bench2` 最后一次实测 `t_cats_fetch_parse_ms=3.2 / t_slice_fetch_parse_ms=2.4 / t_group_ms=0.3`（localhost）、`30.1 / 3.7 / 0.5`（8 Mbps）。

**如果要让 ATC 码也直接出商品名行（不做成分摘要）**：需要给 1,153 个 L1–L4 码各生成 top200 切片，实测合计 **30.99 MB raw / 4.97 MB gzip，中位 30.0 KB/码**（`size_atc_slices.py`）。dist 现在 880.2 MB，加得下，但换来的只是「ATC 码查询也省 1 次 core fetch」——**不建议**，用成分摘要 + 后台补全即可（见下）。

### 2.5 失败降级 / 无 JS / 老链接

| 场景 | 行为 |
|---|---|
| `cats.json` 404 / JSON 坏 / 老缓存 | `loadCatx()` catch → `CATX=null` → `startFastLane()` 返回 false → 走今天的 `loadShardedIndex()` / `loadIndex()`，行为逐字节不变（`build.py:5089-5122` 的错误 UI 也不变） |
| 切片文件 404 | `renderCategoryFast()` catch → `loadIndex()` 老路径（用户最多多等一次，不会白屏） |
| `core.json` 仍然慢/失败 | 切片渲染不受影响；`loadIndex(true)` 失败时 `build.py:5110-5113` 只在 console 警告，保留分片/切片视图 |
| 无 JS | 16 个静态 `cat/<id>.html`（`build.py:9568-9622`）+ 1,155 个 `atc/<code>.html`（`build.py:9467`）已经在；`/atc.html` 是入口。建议顺手把 66 个口语词作为 `?q=` 链接加到 `/atc.html` 的大类卡片下（纯 HTML，不依赖 JS） |
| 老链接 `?q=退烧药` | URL 协议不动（`syncURL()`），修完这个词从「0 结果」变成「大类结果」，链接不 404 |
| 版本号/缓存 | `cats.json` 与 `categories.json` 一样**不带 `?v=`**（数据产物不进 `BUILD_V`，`build.py:78-90` 明确「刻意不含数据库」）；缓存 TTL 与 HTML 同量级（10 分钟），不会出现「HTML 新、索引旧」以外的偏差 |

### 2.6 风险与回归

- **风险 A（首查行为变化）**：切片只有 top200（今天 `hits.slice(0,200)` 也是 200，口径一致），但**排序规则换了**（见 §4），同一查询的首屏行会变——这是本批想要的变化，但发布说明要写。
- **风险 B（后台补全抖动）**：`loadIndex(true)` 完成后会 `render()` 重绘（`build.py:5105`），若用户已滚动，可能出现一次重排。缓解：切片路径进入时置 `POOL_READY=true`（让 `partial` 逻辑生效，`build.py:4654`），或在 `renderCategoryFast` 里记住 `scrollY` 复原。
- **风险 C（体积/lint 门槛）**：`deploy/ci_checks.py:44-55` 有 `CORE_MIN_BYTES=10_000_000` / `DIST_MIN_FILES=24_000` / `REQUIRED_DIST_FILES`；新增文件只增不减，建议把 `data/idx/cats.json` 加进 `REQUIRED_DIST_FILES`（缺了就是构建不完整）。`deploy/verify_live.py:49-53` 的 core gzip 区间（2.5–12 MB）不受影响。
- **回归清单**：`& $py site/build.py` 到 `== done ==`；本地 `& $py serve.py 8000` 后手查 3 类查询（大类词 / ATC 码 / 普通药名）各 2 条，确认「首屏 < 1 s、结果条数与旧版一致（±排序）」；`& $py deploy/ci_checks.py --fast`；发布前 `& $py deploy/verify_live.py`（core 体积区间）；再跑 §5 的评测。

---

## 3. 问题 2：口语大类别名客户端不同步

### 3.1 lib 里现成的词表（现查）

| 项 | 位置 | 规模 |
|---|---|---|
| 16 大类快照 | `lib/categories.py:21-118` `CATEGORY_SNAPSHOT` | 16 条（id/url/prefixes/4 语 labels/aliases） |
| **口语别名** | `lib/categories.py:121-153` **`COLLOQUIAL_ALIASES`** | **66 条**（`len(COLLOQUIAL_ALIASES)=66`），覆盖 16 类 |
| 匹配函数 | `lib/categories.py:179-203` `match_category()` | 先 label/alias（客户端口径），再口语词 |

客户端这边：`site/build.py:9686-9708 build_categories_json()` 写 `data/categories.json`，`items` 只由 `CONSUMER_CATEGORIES`（`build.py:8944`）的 `labels` + `[labels.en, id]` 组成；**`COLLOQUIAL_ALIASES` 一次都没被读**。客户端 `catHit()`（`build.py:4563-4577`）只认 `CATS.categories[].labels/aliases`。
现查：`categories.json` 词表 4,073 个归一化词（含 1,154 个 ATC 码及其 4 语类名），**66 条口语词里 52 条不在其中**（14 条恰好等于官方 label，例如「胃药」「降糖药」「减肥药」「抗过敏药」「抗抑郁药」）。

`catHit('退烧药')` 实测返回 `null`（`bench.html` 输出 `probes:[["退烧药",3.2,null]]`），且 `name_key` 里没有任何名字含「退烧药」（`contains-hits 0`），`aliases.json` 也没有这条 → **真的 0 结果**，不是「被别的层接住」。

### 3.2 差异清单：lib 有、客户端没有的 52 条（每条给 ATC4 码 + 成分集）

> 数据源：`lib/categories.py` 的目标大类 + `data/drugs.db` 现查（active 产品）。`ATC4` 为该大类 prefix 下现存的 4 位码；成分按 active 产品数降序取 top5。

| # | 口语词 | lib 目标大类 | ATC 前缀 | ATC4 码 | 成分（active 产品数 top5） |
|---|---|---|---|---|---|
| 1 | 退烧药 | analgesics | N02/M01A | N02B/M01A/N02A/N02C | Acetaminophen(10002)、Ibuprofen(3216)、Diclofenac(2036)、Pregabalin(1610)、Naproxen(1125) |
| 2 | 退燒藥 | analgesics | N02/M01A | N02B/M01A/N02A/N02C | 同上 |
| 3 | 退热药 | analgesics | N02/M01A | N02B/M01A/N02A/N02C | 同上 |
| 4 | 退熱藥 | analgesics | N02/M01A | N02B/M01A/N02A/N02C | 同上 |
| 5 | 发烧药 | analgesics | N02/M01A | N02B/M01A/N02A/N02C | 同上 |
| 6 | fever medicine | analgesics | N02/M01A | N02B/M01A/N02A/N02C | 同上 |
| 7 | fever reducer | analgesics | N02/M01A | N02B/M01A/N02A/N02C | 同上 |
| 8 | painkiller | analgesics | N02/M01A | N02B/M01A/N02A/N02C | 同上 |
| 9 | pain killer | analgesics | N02/M01A | N02B/M01A/N02A/N02C | 同上 |
| 10 | 止痛药 | analgesics | N02/M01A | N02B/M01A/N02A/N02C | 同上 |
| 11 | 止痛藥 | analgesics | N02/M01A | N02B/M01A/N02A/N02C | 同上 |
| 12 | 消炎药 | antibiotics | J01 | J01C/J01X/J01M/J01F/J01E/J01D/J01A/J01G/J01B | Amoxicillin(2815)、Metronidazole(2455)、Levofloxacin(2156)、Azithromycin(1752)、Erythromycin(1218) |
| 13 | 消炎藥 | antibiotics | J01 | 同上 | 同上 |
| 14 | antibiotic | antibiotics | J01 | 同上 | 同上 |
| 15 | stomach medicine | acid-related | A02 | A02B/A02A/A02D/A02X | Omeprazole(1895)、Sodium Bicarbonate(1144)、Esomeprazole(933)、Pantoprazole(925)、Famotidine(815) |
| 16 | 降血压药 | antihypertensives | C02/C03/C07/C08/C09 | C03A/C08C/C09C/C07A/C08D/C09A/C03C/C03D/C03B/C02C/C02A/C02D/C03X/C09D/C02K/C03E/C08E/C09X/C09B/C02L/C02B | Hydrochlorothiazide(2955)、Amlodipine(2507)、Valsartan(1778)、Telmisartan(1124)、Metoprolol(1057) |
| 17 | 降壓藥 | antihypertensives | 同上 | 同上 | 同上 |
| 18 | blood pressure medicine | antihypertensives | 同上 | 同上 | 同上 |
| 19 | blood pressure medicines | antihypertensives | 同上 | 同上 | 同上 |
| 20 | 降糖藥 | diabetes | A10 | A10B/A10X/A10A | Metformin(2889)、Sitagliptin(872)、Gliclazide(499)、Glipizide(423)、Glimepiride(398) |
| 21 | 糖尿病药 | diabetes | A10 | 同上 | 同上 |
| 22 | 糖尿病藥 | diabetes | A10 | 同上 | 同上 |
| 23 | diabetes medicine | diabetes | A10 | 同上 | 同上 |
| 24 | 減肥藥 | weight-loss | A08（lib 旧口径） | A08A（旧） / 见 §3.3 注 | Orlistat(250)、Phentermine(143)、Diethylpropion(24)、Sibutramine(9)、Rimonabant(4) |
| 25 | weight loss medicine | weight-loss | 同上 | 同上 | 同上 |
| 26 | 感冒药 | cold-medicine | R05/N02BE/R06（lib 旧口径） | N02B/R05D/R05C/R06A/R05F/R05X/R05（旧） / 见 §3.3 注 | Acetaminophen(10002)、Dextromethorphan Hydrobromide(2217)、Guaifenesin(1949)、Chlorpheniramine(1352)、Chlorphenamine(1164) |
| 27 | 感冒藥 | cold-medicine | 同上 | 同上 | 同上 |
| 28 | cold medicine | cold-medicine | 同上 | 同上 | 同上 |
| 29 | allergy medicine | allergy | R06 | R06A | Chlorpheniramine(1352)、Chlorphenamine(1164)、Loratadine(975)、Cetirizine(834)、Doxylamine(557) |
| 30 | 抗凝藥 | anticoagulants | B01 | B01A | Aspirin(2149)、Rivaroxaban(872)、Enoxaparin(442)、Ticagrelor(406)、Heparin(403) |
| 31 | blood thinner | anticoagulants | B01 | 同上 | 同上 |
| 32 | blood thinners | anticoagulants | B01 | 同上 | 同上 |
| 33 | 他汀 | statins | C10AA | C10A | Atorvastatin(1795)、Rosuvastatin(1278)、Simvastatin(1249)、Pravastatin(507)、Pitavastatin(224) |
| 34 | statin | statins | C10AA | 同上 | 同上 |
| 35 | 降脂药 | statins | C10AA | 同上 | 同上 |
| 36 | 降脂藥 | statins | C10AA | 同上 | 同上 |
| 37 | beta阻滞剂 | beta-blockers | C07 | C07A | Metoprolol(1057)、Propranolol(609)、Bisoprolol(575)、Atenolol(517)、Carvedilol(495) |
| 38 | beta 阻滞剂 | beta-blockers | C07 | 同上 | 同上 |
| 39 | beta blocker | beta-blockers | C07 | 同上 | 同上 |
| 40 | antidepressant | antidepressants | N06A | N06A | Venlafaxine(811)、Duloxetine(590)、Sertraline(573)、Fluoxetine(531)、Mirtazapine(508) |
| 41 | 哮喘药 | asthma-copd | R03 | R03D/R03A/R03B/R03C | Montelukast(651)、Albuterol(574)、Budesonide(501)、Aminophylline(357)、Salmeterol(329) |
| 42 | 哮喘藥 | asthma-copd | R03 | 同上 | 同上 |
| 43 | asthma medicine | asthma-copd | R03 | 同上 | 同上 |
| 44 | inhaler | asthma-copd | R03 | 同上 | 同上 |
| 45 | 激素 | corticosteroids | H02 | H02A/H02C | Betamethasone(749)、Prednisone(506)、Deflazacort(80)、Fludrocortisone(71)、Cortisone(35) |
| 46 | 类固醇 | corticosteroids | H02 | 同上 | 同上 |
| 47 | 類固醇 | corticosteroids | H02 | 同上 | 同上 |
| 48 | steroid | corticosteroids | H02 | 同上 | 同上 |
| 49 | antiviral | antivirals | J05 | J05A | Ribavirin(818)、Acyclovir(727)、Oseltamivir(446)、Ganciclovir(358)、Potassium Dehydroandrographolide Succinate(322) |
| 50 | 皮肤药 | dermatologicals | D | D02A/D02B/D04A/D11A/D07A/D08A/D06A/D10A/D01A/D01B/D05A/D10B/D06B/D05B/D03A/D07B/D07X/D03B/D09A/D07C | Zinc Oxide(4763)、Octisalate(3852)、Avobenzone(3258)、Octocrylene(3182)、Homosalate(2983) |
| 51 | 皮膚藥 | dermatologicals | D | 同上 | 同上 |
| 52 | skin medicine | dermatologicals | D | 同上 | 同上 |

> 生成脚本：`.tmp/audit/gen_tables.py` → `.tmp/audit/tables.md`（可复跑，含完整表格）。

### 3.3 顺带发现的漂移：lib 快照本身就是旧的（9/16 类不一致）

`lib/categories.py:21-118` 自称「快照自 `site/dist/data/categories.json`（站点 v0.7.1）」，现查与 v0.10.1 实际产物**有 9 个类不一致**（`tests/test_lib_atc_category.py::test_snapshot_sync_with_dist` 现在就红，见 3.5）：

| 大类 | 字段 | lib（旧） | 站点现产物（`build.py:8944`） |
|---|---|---|---|
| antihypertensives | zh-Hant | 降壓藥 | 降血壓藥 |
| diabetes | zh-Hant | 降糖藥 | 降血糖藥 |
| **weight-loss** | **prefixes** | **A08** | **A08/A10BJ/A10BX16** |
| weight-loss | zh-Hant | 減肥藥 | 減重藥 |
| **cold-medicine** | **prefixes** | **R05/N02BE/R06** | **R05/N02BE** |
| cold-medicine | zh / zh-Hant | 感冒药 / 感冒藥 | 感冒咳嗽药 / 感冒咳嗽藥 |
| anticoagulants | zh / zh-Hant | 抗凝/抗血栓 | 抗凝药 / 抗凝血藥 |
| beta-blockers | zh-Hant | β受體阻滯劑 | β受體阻斷劑 |
| antidepressants | zh-Hant | 抗抑鬱藥 | 抗憂鬱藥 |
| asthma-copd | zh / zh-Hant | 哮喘/慢阻肺用药 | 哮喘·慢阻肺吸入剂 |
| corticosteroids | zh / zh-Hant | 激素/糖皮质激素 | 激素类 / 荷爾蒙類 |

影响：若直接拿 lib 的 prefixes 当验收期望，`weight-loss` 会漏掉 GLP-1（A10BJ/A10BX16 → Semaglutide 180、Tirzepatide 141，见 §4 的 24 例）、`cold-medicine` 会多算 R06 抗组胺（Chlorpheniramine 1352 被算进感冒药）。**所以同步方向必须是 `build.py`（线上真相）→ 一处数据源 → lib/客户端**，不能反过来。

### 3.4 同步改法（一处生成，客户端 + lib 复用）

1. **唯一数据源**：把 `CONSUMER_CATEGORIES`（`build.py:8944` 起，含 desc/notes）与新增 `COLLOQUIAL_ALIASES`（66 条，从 `lib/categories.py` 搬来）收进 `lib/categories.py` 的**数据区**，`site/build.py` 顶部 `from lib.categories import CONSUMER_CATEGORIES, COLLOQUIAL_ALIASES`（`build.py` 现在不 import lib，需在 `ROOT` 定义后 `sys.path.insert(0, str(ROOT))`）。`lib/categories.py` 的 `CATEGORY_SNAPSHOT` 删除，`match_category()` 直接读 `CONSUMER_CATEGORIES`。
2. **两处产物同源生成**：`build_categories_json()`（`build.py:9686-9708`）里，把口语词**并进对应大类条目的 `aliases`**（不是新增 1,170 条 item——`catHit()` 本来就遍历 `aliases`，旧客户端也会立刻生效）：
   ```python
   by_id = defaultdict(list)
   for word, cat_id in COLLOQUIAL_ALIASES.items():
       by_id[cat_id].append(word)
   for cat in CONSUMER_CATEGORIES:
       labels = dict(cat["labels"])
       aliases = [labels.get("en", ""), cat["id"], *by_id.get(cat["id"], [])]
       items.append({"kind": "cat", "id": cat["id"], "url": f'cat/{cat["id"]}.html',
                     "prefixes": list(cat["prefixes"]), "labels": labels,
                     "aliases": [a for a in aliases if a]})
   ```
   新 `build_cat_word_index()`（§2.3）写 `cats.json` 的 `words` 时用同一份表（`COLLOQUIAL_ALIASES` + labels + id）。
3. **客户端只读一处**：`catHit()`（`build.py:4563-4577`）改成先查 `CATX.words`（归一化词 → `cat:`/`atc:`，快车道用），查不到再走老 `CATS.categories` 循环（没拿到 cats.json 也能认 52 个词，靠上面第 2 步）。
4. **防遮蔽（重要）**：`catHit()` 在 `render()` 里排在名字检索之前（`build.py:4636`）。现查 66 条词里 **`antibiotic` 同时是 `name_key`**（`name_key.norm='antibiotic'` 有 1 条），`感冒药/消炎药/胃药/他汀` 在 `name_key` 里还有 2–29 条 `contains` 命中。两种改法（选一）：
   - **轻**：把这 1 条例外从 alias 列表里去掉（`antibiotic` 已由英文 label `Antibiotics` 覆盖），并给 `COLLOQUIAL_ALIASES` 加一条构建期断言：任何口语词都不得是 `name_key.norm` 的全等值；断言失败就构建报错（比线上遮蔽好）。
   - **严**：`catHit()` 命中后先查「这个词有没有 exact name_key」，有则走名字检索。

   另外 `感冒药 / 消炎药 / 胃药 / 他汀` 现在有 `contains` 名字命中（2–29 条），改后这些查询会从「几条名字包含匹配」变成「整类候选集」——这是产品意图，但要在发布说明里写清，并在验收里加一条「搜 `消炎药膏`（真实商品名）仍返回商品名结果」。
5. **验收查询（12 词，现查期望；客户端修复前 vs 后）**

| 查询 | 客户端现状 | 修复后应命中 | 期望首个成分（active 产品数） |
|---|---|---|---|
| 退烧药 | **0 结果** | analgesics（N02/M01A） | Acetaminophen(10002) |
| 消炎药 | 2 条 `contains` 名字命中（非整类） | antibiotics（J01） | Amoxicillin(2815) |
| 胃药 | 命中 cat:acid-related | acid-related（A02） | Omeprazole(1895) |
| 降血压药 | **0 结果** | antihypertensives（C02/03/07/08/09） | Hydrochlorothiazide(2955) |
| 降糖药 | 命中 cat:diabetes | diabetes（A10） | Metformin(2889) |
| 减肥药 | 命中 cat:weight-loss | weight-loss（A08/A10BJ/A10BX16） | Orlistat(250) |
| 感冒药 | 3 条 `contains` 名字命中 | cold-medicine（R05/N02BE） | Acetaminophen(10002) |
| 抗过敏药 | 命中 cat:allergy | allergy（R06） | Chlorpheniramine(1352) |
| 抗凝药 | 命中 cat:anticoagulants（靠 label） | anticoagulants（B01） | Aspirin(2149) |
| 他汀 | 29 条 `contains` 名字命中 | statins（C10AA） | Atorvastatin(1795) |
| 抗抑郁药 | 命中 cat:antidepressants | antidepressants（N06A） | Venlafaxine(811) |
| 皮肤药 | **0 结果** | dermatologicals（D） | Zinc Oxide(4763) |

> 期望值由 `.tmp/audit/alias_diff.py` 现查 DB 得出（`lib.match_category` + `COUNT(DISTINCT product_id)`）。

### 3.5 风险与回归

- **风险 A（遮蔽）**：见 3.4-4；必须为「口语词 = 真实 name_key」加保护，验收里加一条：搜 `消炎药膏`（真实商品名）仍返回商品名结果，不被整类化。
- **风险 B（期望值随 prefixes 同步而变）**：`tests/search_eval/gen_atc_category_cases.py:96-117` 的期望来自 `lib.categories`；同步后 `cold-medicine`（去掉 R06）与 `weight-loss`（加 A10BJ/A10BX16）的 `top_substance()` 会变 → **必须重跑生成器 + 全量 `run_ci.py`**，并在报告里记录用例期望的变化（不许手改用例）。
- **风险 C（现有单测已红）**：`& $py -m unittest tests.test_lib_atc_category -v` 现在 **14 tests / 1 failure**（`test_snapshot_sync_with_dist`: `'降壓藥' != '降血壓藥'`）。同步后应变绿；注意 CI 只跑 `etl/lib/mobile`（`deploy/ci_checks.py:121-124`），**没跑 `tests.test_lib_atc_category`**，建议顺手加进 CI（否则漂移还会回来）。
- **回归清单**：`& $py -m unittest tests.test_lib_atc_category -v`（14）、`& $py -m unittest discover -s lib -t lib`、`& $py tests/search_eval/run_ci.py`（全量）、`& $py tests/trilingual/run_tests.py`（72 例）、建站后三语各抽 3 条口语词。

---

## 4. 问题 3：大类结果排序（3/24 未进 Top5）

### 4.1 24 条期望用例与 3 条失败（现跑）

用例在 `tests/trilingual/cases_v4.json`（由 `tests/search_eval/gen_atc_category_cases.py` 生成：C 段 16 条 = 16 大类四语 label 轮换，D 段 8 条 = 口语词；合计 **24 条 `category`**，另有 13 条 `atc`，共 37 条）。期望 = `top_substance(prefixes)`，即**该类别里 active 产品数最多的成分**（`gen_atc_category_cases.py:40-52`），`min_tier="top5"`。

```powershell
& $py tests/search_eval/run_ci.py --category category --json .tmp/audit/ci_cat.json
# → must_hit：Top-5 21/24 (87.5%，门槛 ≥95%)，Top-1 17/24
```

| case | 语言 | 查询 | 期望成分 | 现状 | 当前 Top1 |
|---|---|---|---|---|---|
| v4-category-0001 | en | Blood-pressure medicines | Hydrochlorothiazide | **未进前 5** | Amlodipine |
| v4-category-0007 | zh | 抗过敏药 | Chlorpheniramine | **未进前 5** | Acetaminophen+Chlorphenamine+Pseudoephedrine（复方） |
| v4-category-0012 | zh-Hant | 抗抑鬱藥 | Venlafaxine | **未进前 5** | Bupropion |

其余 21 条通过，但 4 条只是「Top5 里混进来」（`rank=1/2`：Antibióticos 1、Estatinas 1、Asthma/COPD 1、Hormonas esteroideas 2）。

### 4.2 根因（文件:行 + 数字）

1. `lib/search.py:771`：`result.sort(key=lambda c: (-c.score, -c.n_products, len(c.key_id), c.brand.lower()))`。大类/ATC 卡片的 `score` 完全相同（`_score_card` 里 tier 都是 `category`/`atc`，`_score_card` `lib/search.py:655-678`），所以**实际排序键 = 单张卡的 `n_products`**。
2. 一张卡 = `(key_id, country, 成分组合, form_base, release)`（`lib/search.py:741-743`）。同一成分被拆到很多 key/国家/剂型上 → 每张卡都很小。实测 `抗过敏药`（R06）：
   - 复方「小儿氨酚黄那敏颗粒」一张卡 **713 条**；
   - Chlorphenamine（单成分）一张卡 277 条；Chlorpheniramine 分散在 **37 张卡**，合计 268 条，最大的卡远小于 713 → 前 5 名被复方/其他成分占满。
3. 更上游还有一刀：`_keys_by_atc_prefixes()`（`lib/search.py:804-822`）先按 **key 级** `n` 取 **top200 key**，再交给 `_cards_for_keys()`。成分命名越碎（品牌名多、每名条数少），越容易被这 200 个 key 截掉——Chlorpheniramine 的 1,352 条产品大部分落在 200 名之外。
4. 客户端同样口径：`renderATC`（`build.py:4538`）与 `renderCategory`（`build.py:4597`）都 `hits.sort((a,b)=>(b.n||0)-(a.n||0))`，`n` 是**条目级**产品数；`groupByIngredient()`（`build.py:3776-3786`）只是按首次出现顺序分组，不重排。

### 4.3 方案对比（只改排序键/去重，不改数据）

在 `.tmp/audit/` 里把 24 条用例的卡片全量算出来后，试了 7 种排序键（`rank_variants.py` / `rank_h.py`；`rank_of()` 与 `run_ci.py:93-104` 完全同口径）：

| 方案 | 排序键 | 24 例 Top5 | 13 例 ATC Top5 |
|---|---|---:|---:|
| A（现状） | 单卡 `n_products` | 21/24 | 13/13 |
| B | 卡内成分的**卡片级**合计，取 max | 23/24 | — |
| C | 同上取 min | 23/24 | — |
| D | 卡内成分合计求和 | 22/24 | — |
| E | 单成分卡优先 + B | 23/24 | — |
| F | 卡内成分合计平均 | 23/24 | — |
| **H（推荐）** | **成分在该类别内的 active 产品总数（DB 口径），取 max** | **24/24** | **13/13** |

H 修掉的三条：`0001` Hydrochlorothiazide 2,955 条（DB 口径）→ 第 1；`0007` Chlorpheniramine 1,352 > Chlorphenamine 1,164 → 第 1（复方卡的 `max` 也用它命中的那个成分算，不再被 713 条复方顶掉）；`0012` Venlafaxine 811 条 → 第 1。
H 对 13 条 ATC 用例不降级（13/13，其中 2 条从 rank 1 升到 0）。副产物：**Top-1 从 17/24 变 24/24**。

> 说明：H 不是「照测试调参」——24 条用例的期望定义就是「该类别里 active 产品最多的成分」，H 让结果顺序与这个定义一致；同时它就是客户端已有的「按成分聚合」展示（`groupByIngredient`）的自然排序。反过来，现状（按单卡条数）会让「复方 + 命名碎片化」系统性占优，属于产品缺陷。

### 4.4 改法（可直接照抄的 diff）

```diff
--- a/lib/search.py
+++ b/lib/search.py
@@ class SearchIndex
+    def _ingredient_totals(self, prefixes: list[str]) -> dict[str, int]:
+        """成分在本类别内的 active 产品数（大类/ATC 排序用；与 DB 口径一致）。"""
+        prefixes = [p for p in prefixes if p]
+        if not prefixes:
+            return {}
+        cond = " OR ".join("s.atc LIKE ?" for _ in prefixes)
+        out: dict[str, int] = {}
+        for r in self.db.execute(
+                f"""SELECT s.inn_en AS inn, COUNT(DISTINCT p.product_id) AS n
+                    FROM substance s JOIN variant v ON v.substance_id = s.substance_id
+                    JOIN product_component pc ON pc.variant_id = v.variant_id
+                    JOIN product p ON p.product_id = pc.product_id AND p.status = 'active'
+                    WHERE s.atc IS NOT NULL AND ({cond})
+                    GROUP BY s.substance_id""", tuple(p + "%" for p in prefixes)):
+            out[r["inn"]] = max(out.get(r["inn"], 0), r["n"])
+        return out
+
+    def _order_by_ingredient(self, totals: dict[str, int]):
+        """成分聚合排序：同一成分的卡相邻（=组内去重），组间按成分产品数。"""
+        def key(c: Card):
+            hit = max((totals.get(s, 0) for s in c.substances if s), default=0)
+            return (-hit, -c.n_products, len(c.key_id), c.brand.lower())
+        return key
```

```diff
@@ def _cards_for_keys(self, key_ids, tier_of, n, country, include_status, limit):
-    def _cards_for_keys(self, key_ids: list[str], tier_of: dict[str, str], n,
-                        country: str | None, include_status: tuple[str, ...],
-                        limit: int) -> tuple[list[Card], str]:
+    def _cards_for_keys(self, key_ids: list[str], tier_of: dict[str, str], n,
+                        country: str | None, include_status: tuple[str, ...],
+                        limit: int, order=None) -> tuple[list[Card], str]:
         ...
-        result.sort(key=lambda c: (-c.score, -c.n_products, len(c.key_id), c.brand.lower()))
+        result.sort(key=order or (lambda c: (-c.score, -c.n_products,
+                                             len(c.key_id), c.brand.lower())))
         return result[:limit], ""
```
（`order=None` 的默认行为与今天逐字节一致 → 名字检索的调用点 `lib/search.py:930` 一行不用改。）

```diff
@@ def _search_atc(self, code, query, country, limit, include_status):
-        cards, note = self._cards_for_keys([k for k, _ in keys],
-                                           {k: "atc" for k, _ in keys},
-                                           n, country, include_status, limit)
+        cards, note = self._cards_for_keys(
+            [k for k, _ in keys], {k: "atc" for k, _ in keys},
+            n, country, include_status, 200,          # 与今天 hits.slice(0,200) 同上限
+            order=self._order_by_ingredient(self._ingredient_totals([code])))
+        cards = cards[:limit]
@@ def _search_category(self, match, query, country, limit, include_status):
-        cards, note = self._cards_for_keys([k for k, _ in keys],
-                                           {k: "category" for k, _ in keys},
-                                           n, country, include_status, limit)
+        cards, note = self._cards_for_keys(
+            [k for k, _ in keys], {k: "category" for k, _ in keys},
+            n, country, include_status, 200,
+            order=self._order_by_ingredient(self._ingredient_totals(prefixes)))
+        cards = cards[:limit]
```

要点：
- **必须先取全量卡再排**（现状 `limit` 截断发生在排序后，但 top200-key 的截断仍在 `_keys_by_atc_prefixes:821`——若某成分完全落在 200 名之外，H 也救不回来；本批 24/24 说明当前数据下够用。真出现「成分 0 张卡」时再考虑把 key 上限按成分覆盖度扩到 400，属于下一批）。
- 成本：`_ingredient_totals()` 一次 join（`lib/search.py:777` 的注释给的是同量级「约 1–2 s 一次全表 join」，只在 ATC/大类查询触发，不进名字检索冷启动）。
- **客户端同步改**（否则线上与 CI 口径不一致）：`renderCategory` / `renderATC` 里 `hits.sort(...)` 之前，用 `CATX.cats[].ing`（或 `atc-ing.json`）建 `ingWeight` 映射，把排序键换成 `(ingWeight[x] 降序, e.n 降序)`；`groupByIngredient()` 不用改（它只按出现顺序分组，排序正确后自然成分聚合）。

### 4.5 对三语评测的影响（`tests/trilingual/run_tests.py`，72 例 / 354 查询）

- 现查：`72 cases / 354 queries`（脚本内 `CASES` 计数），其中 **0 条查询会命中 `match_category()`**（含 66 条口语词；用 `lib.categories.match_category` 全量跑过，结果 `category-word hits: 0`）。
- `search()` 的类别分支（`lib/search.py:913-915`）只有 `match_category` 命中才会走 `_search_category`；本改动只碰 `_search_atc` / `_search_category` 的排序键，**名字检索路径（`_cards_for_keys` 的默认排序、`_score_card`）一行不改**。
- 因此 **三语 72 例 / 354 查询不受影响**，但发布前仍按门槛跑一遍（`ci_checks.py` 的 `TRILINGUAL_MIN_PASS=68`，`deploy/ci_checks.py:41-42`）。
- 需要重跑的还有 `tests/search_eval/run_ci.py` 全量（v4 = 548 例，其中 ATC/大类 37 例）——预期 `category` 24/24、`atc` 13/13，总 Top-5 只升不降。

---

## 5. 构建增量体积汇总

| 改动 | 新增产物 | raw | gzip | 文件数 |
|---|---|---:|---:|---:|
| #2 词表同步 | `categories.json` 里 16 个大类条目的 `aliases` 追加 52 个口语词（每词 ≈15 B） | +≈0.001 MB | +≈0.001 MB | 0 |
| #1 轻量类别索引 | `data/idx/cats.json` | 0.023 MB | 0.007 MB | +1 |
| #1 大类切片 | `data/idx/cat-<id>.json` × 16 | 0.65 MB | 0.11 MB | +16 |
| #1 ATC 成分表 | `data/idx/atc-ing.json`（L1–L4，526 码） | 0.062 MB | 0.025 MB | +1 |
| **合计（建议范围）** | | **0.74 MB** | **0.14 MB** | **+18** |
| （可选，不建议）ATC 逐码切片 | 1,153 个 top200 切片 | +30.99 MB | +4.97 MB | +1,153 |

dist 现状 880.2 MB / 121,293 文件（见 `reports/perf-mobile-audit-20261110.md:5`），建议范围内增量 < 0.1%，`deploy/ci_checks.py:45-46` 的 `CORE_MIN_BYTES`/`DIST_MIN_FILES` 不受影响。

---

## 6. 回归验证清单（改完按顺序跑）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# 1) 词表/匹配层
& $py -m unittest tests.test_lib_atc_category -v          # 现 14 例 / 1 failure（快照漂移），同步后应全绿
& $py -m unittest discover -s lib -t lib
# 2) 检索评测（37 条 ATC/大类 + 全量）
& $py tests/search_eval/run_ci.py --category category      # 期望 24/24
& $py tests/search_eval/run_ci.py --category atc           # 期望 13/13
& $py tests/search_eval/run_ci.py                          # 全量，门槛 Top-5 ≥ 95%
# 3) 三语（72 例 / 354 查询；不受本批影响，仍要证明）
& $py tests/trilingual/run_tests.py
# 4) 建站 + 完整性
& $py site/build.py                                        # 等 == done ==
& $py deploy/ci_checks.py --fast
# 5) 体积/线上护栏（发布前）
& $py deploy/verify_live.py --compare-dist                 # core gzip 2.5–12 MB 区间
```

建站后手工抽检（三语各 3 条）：`退烧药` / `皮肤药` / `blood pressure medicine` / `C07` / `C10AA` / 普通药名（`泰诺`、`Lipitor 20mg`、`奥美拉唑`）——确认首屏 < 1 s、行数是候选集、无毒理/剂量类文案。

---

## 7. 未做 / 缺口

1. **没有 node**，客户端耗时为 desktop Chrome headless 实测；手机 V8 的绝对耗时按 2–4× 估（未实测），但瓶颈结论（90% 在 core.json 的 gzip 传输 + decodeCore）不受影响。
2. **没跑 `site/build.py`**（只读约束），因此 `cats.json` 的字节以 `.tmp/audit/proto/cats.json` 的原型为准（22,881 B raw / 7,022 B gz，已含 ATC4 码与 `atc_codes`）；正式构建时若每类成分 top16 或 ATC4 码数量变化，会有几 KB 浮动。
3. **200-key 截断**未动：若某成分的卡完全落在 top200 key 之外，§4 的 H 也救不回来；本批 24/24 说明当前数据够用，留作下一批观察项（可加断言：每类 Top1 成分必须有卡）。
4. **ATC 逐码切片的 UX 取舍**未拍板：本报告建议「成分摘要 + 后台补全」，若要求 ATC 码也一眼看到商品名行，则要 +31 MB raw（不建议）。
5. 老客户端（缓存里的旧 `app.js`）不认识 `cats.json`，但会照旧走 core；`categories.json` 里追加口语 alias 后，**旧客户端也能认出这 52 个词**——这是本批的额外收益，也是回归时要验的点（用 `?legacy=1` 各查 1 条）。
