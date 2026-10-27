# 搜索增强接入 build.py + APP_JS（task-28）

> 日期：2026-10-27 · 任务：task-28 · 状态：**已接入 `site/build.py`（独占文件，UI P0/i18n/统计均保留）**
> 构建验证目录：`.tmp/dist-search/{old,new}`（old = 接入前快照 `build_before.py` 构建，new = 接入后）
> 未改 `site/dist`、`data/drugs.db`；未跑 git / 发布。
> 接入后 `site/build.py`：1768→3097 行（+369 / −40），sha256 `8199cb26…`；生成 `assets/app.js` 47,912 B（gzip 16.6 KB，原 37,258 B/13.5 KB）。

---

## 1. 结论

| 指标 | 接前（线性扫描） | 接后（运行时派生层） | 变化 |
|---|---:|---:|---|
| 354 三语 Top-1 / Top-5 | 96.89% / 97.18% | **96.89% / 97.18%** | 持平 |
| 30 难例（28 有解）Top-1 | 24/28 | **28/28** | +4 |
| 匹配延迟 P50 / P90 / P99（Node 桌面，热态） | 94.2 / 147.3 / 282.6 ms | **1.11 / 4.24 / 65.8 ms** | P50 ≈85× |
| 首搜新增下载 | — | **0**（派生层在已下载 P1 核心上构建） | — |
| 拼音查询额外下载 | 不支持 | +0.41 MB gz（懒加载一次） | 新能力 |
| 一次性派生构建 | — | light 397 ms + heavy 389 ms（首屏渲染后 idle/下一轮执行） | 新增 |
| DOM 行为（jsdom） | — | 12 项断言 10 通过，7/7 旧版对拍一致，无 JS 错误 | 见 §4 |

- 拼音/首字母：`data/idx/pinyin.json`（1.23 MB raw / **0.41 MB gzip**，22,917 tokens；构建期由 1,582 字拼音字符表生成），客户端只在拉丁查询零命中时懒加载。
- `?legacy=1`：完全走旧 `data/index.json` 全量索引 + 旧线性扫描（DOM 已验证 fetch 只拉 `data/index.json`，结果与旧版一致）。
- P0 懒加载/P1 core.json/候选集/碰撞/国家视图语义保持；DOM 对拍 7 个关键场景渲染结果逐字一致。

---

## 2. 改动清单（file:line，最终快照）

### 2.1 Python 构建侧（`site/build.py`）

| 位置 | 改动 |
|---|---|
| L216 / L347 / L461 | I18N 新增 `parse.match.pinyin`（en `pinyin` / es `pinyin` / zh `拼音`） |
| L2845–L2917 | 新增 `_PINYIN_CHARS_TEXT`（1,582 字「字:拼音」表，来自 pinyin-pro 3.29.5，toneType=none）+ `_pinyin_dict()` + `_pinyin_tokens()` + `encode_pinyin(entries, aliases)`：名字键 token→条目下标；别名（俗称）token→该成分条目（每 token 截断 10 条按 n 降序，控制体积） |
| L2991 | app.js 版本参数替换链新增 `data/idx/pinyin.json?v=<build ts>` |
| L3041–L3044 | `main()` 在 aliases 构建后生成并写 `data/idx/pinyin.json`，打印体积 |

### 2.2 客户端（内嵌 `APP_JS`）

| 位置 | 改动 |
|---|---|
| L644 | 全局：`SEARCH_LAYERS / PY_MAP / PY_P` |
| L874–L906 | `acCompute()` 自动完成：派生层就绪时只遍历候选（exact/连写/前缀/包含，rank 0–3 语义不变），否则回退全表 |
| **L972–L1201** | **新增搜索增强块**（标记 `/* ── 搜索增强（task-28）… */`）：`searchLayersBuildLight()`（exact/compact Map + 前缀排序数组）、`searchLayersBuildHeavy()`（CJK bigram + 拉丁 trigram，含中拉混合名）、`pinyinFetch()` 懒加载、`layerCandidates()` 候选枚举（exact/compact/prefix/contains/CJK-fuzzy/拼音/typo；有确定命中时不做模糊/拼音）、`collectHits()` 统一匹配（派生路径与旧两遍扫描共用 addHit/tier/排序；候选按 IDX 下标升序处理保证同分稳定排序；模糊档按编辑距离细排） |
| L1235–L1244 | `render()` 改用 `collectHits(...)`；零命中拉丁查询触发 `pinyinFetch()` 后重渲 |
| L1525–L1531 | `loadIndex()` 成功后：`searchLayersBuildLight()` 立即执行，`searchLayersBuildHeavy()` 置 `setTimeout(0)`（首个结果仍走旧路径，不阻塞首屏；`?legacy=1` 不构建） |
| 回退 | 派生层构建抛错 → `SEARCH_LAYERS=null`，`collectHits` 走旧线性扫描；昵称/`onlyUnmapped` 查询仍走旧全表路径（语义不变） |

---

## 3. 基准（354 条三语 + 30 难例；`bench_after.mjs` 直接 eval 生成后的 app.js）

- 数据：`site/dist/data/index.json` 126,915 键（用 old/new 同一份索引做前后对比，排除 DB 并发漂移）。
- 方法：接前 = `SEARCH_LAYERS=null` 走旧回退分支（与旧 app.js 逐行等价）；接后 = 构建 light+heavy+拼音表后。

| 指标 | 接前 | 接后 |
|---|---:|---:|
| Top-1 / Top-5（354） | 96.89 / 97.18 | 96.89 / 97.18 |
| 难例 Top-1 / Top-5（28 有解） | 24/28、25/28 | **28/28、28/28** |
| 延迟 P50 / P90 / P99 / max | 94.2 / 147.3 / 282.6 / 408 ms | **1.11 / 4.24 / 65.8 / 84 ms** |
| light / heavy 构建 | — | 397 / 389 ms（Node 桌面；手机约 1.5×） |

**逐条差异**（接前 vs 接后，共 384 条）：Top-1 名次不同 8 条、Top-5 集合/顺序不同 8 条、前 200 集合不同 13 条。性质：
1. **难例提升 4 条**（预期内）：`amlopidine` typo→amlodipine；`tainuo/liputuo/fenbide` 拼音→泰诺/立普妥/ibuprofen；`tailuo/taidu` 由模糊噪声变更好/空。
2. **同成分不同条目**（预期内）：如 `amlodipino besilato` 由 amlodipine besylate→amlodipine besilate、`toprol xl` 两个 metoprolol 变体交换，命中成分不变。
3. **模糊档排序微调**：2 条边缘案例命中状态变化、2 条反向变化 → 354 条总 Top-1 净值不变；细分有 ±1 条（en +1，es −1，salt −1，combo +1）。属可接受的排序差异，后续可继续调（见 §6）。

**首搜体积**（gzip9 本机；线上 Pages 约 ×1.02–1.04）：

| 文件 | 接前 | 接后 |
|---|---:|---:|
| `data/index.json`（?legacy=1 用） | 5.80 MB | 5.80 MB（不变） |
| `data/idx/core.json`（P1 首搜主包） | 3.67 MB | 3.67 MB（不变） |
| `data/idx/pinyin.json`（新增，懒加载） | — | **0.41 MB** |
| `assets/app.js` | 13.5 KB | 16.6 KB |

→ 默认首搜仍只下载 core（≈3.86 MB 含 aliases/confused），拼音/首字母功能在首次拼音类查询时追加 0.41 MB；legacy 回滚路径 6.06 MB 不变。

---

## 4. 验证证据

| 验证 | 命令 | 结果 |
|---|---|---|
| Python 编译 | `python -m py_compile site/build.py` | OK |
| 站点构建 | `SITE_OUT=.tmp/dist-search/new python site/build.py` | `== done ==`；12377 drug / 17861 name / 22 pairs；total 160.5 MB；pinyin.json 1.23 MB |
| app.js 语法 | `node --check .tmp/dist-search/new/assets/app.js` | OK |
| 基准 | `node .tmp/dist-search/bench_after.mjs` | §3（含 384 条逐条 diff、体积） |
| **DOM 行为**（jsdom 手工执行 i18n.js+app.js，fetch 指向本地 dist） | `node .tmp/dist-search/dom_test.mjs` | **12 项断言 10 通过；7/7 旧版对拍渲染逐字一致；new/legacy 均无 JS 运行时错误** |
| `?legacy=1` | 同上（`?legacy=1` 场景） | 只拉 `data/index.json`，结果非空，与旧版一致 |

DOM 通过项：exact（Lipitor→Atorvastatin）、别名（芬必得→昵称提示+布洛芬）、国家视图（US 生效，解析条显示 `exact · country view`）、拼音懒加载（fetch log 出现 `data/idx/pinyin.json`）、typo（atovastatin→Simvastatin 组内）、零结果、CJK+CN、legacy、首次搜索不拉 index.json、无 JS 错误。
2 项未过（非产品缺陷，已定位）：
1. **ARTG 断言**：`data/artg.json` 已成功拉取且渲染流程无异常，但 `Mylanta` 在该数据里没有匹配行（旧版同样 0 行，对拍 `Mylanta` 一致）→ 断言对数据过严。
2. **拼音 DOM 场景**：测试脚本在上一场景遗留 `country=US` 的选择状态下执行 `tainuo`，国家视图用到了非预期条目（`Eplontersen`）；同查询在不带国家状态下通过（bench Top-1=泰诺）。已列为遗留验证项（DOM 测试需重置国家），不是接入代码路径的回归。

数据环境说明：构建期间 `data/drugs.db` 被其他并行任务更新（old 构建 aliases 1,456 条 → new 1,119 条），因此 old/new 的 `aliases.json` 不同；**基准统一用同一份旧 `index.json/aliases` 做前后对比**，DOM 对拍只比较由 `index.json` 决定的 7 个关键场景（均一致）。

---

## 5. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 派生层构建失败 | `try/catch` → `SEARCH_LAYERS=null` → 自动回退旧线性扫描；`?legacy=1` 完全绕过 |
| 排序差异（模糊档） | 354 总 Top-1/Top-5 不降、难例 +4；`tier/addHit/排序`未改；如需严格 100% 顺序一致可关闭派生层（见回滚） |
| 移动端内存 | light+heavy 派生结构约 +27 MB（IDX 85 MB 之上）；heavy 在首屏后 setTimeout 构建，失败自动回退；后续可懒构建 trigram/打平 `Uint32Array` |
| 首屏后 0.4–0.8 s 窗口 | 首个查询仍走旧路径（与现状一致），heavy 就绪后自动走新路径 |
| 拼音多音字/别名截断 | 拼音只做增量兜底；别名 token 每词至多 10 条（控制 0.41 MB 体积），完整品牌列表仍可通过中文俗称/结果页获得 |
| 与并行 i18n 任务冲突 | build.py 已交回；本次改动均为新增块（标记清晰），i18n 只需在 I18N 三语字典上加键 |
| **回滚** | ① URL `?legacy=1`；② 删除/注释 `/* ── 搜索增强 … end */` 块 + `collectHits` 改回旧两行循环（保留 `build_before.py` 可对照）；③ 不发布即可回退（`site/dist` 未改）。`pinyin.json` 不生成也不影响旧逻辑（无引用） |

---

## 6. 遗留问题 / 后续建议

1. DOM 测试修正 `country` 残留状态后复跑拼音场景（脚本问题，5 分钟）。
2. 模糊档排序可再调（距离→n 的组合），把 354 条细分 ±1 收敛；不阻塞发布。
3. 昵称/别名类查询仍走旧全表路径（P99 65–84 ms）：可后续用「sid→ids 懒加载映射」把昵称路径也纳入派生层。
4. heavy 构建（trigram ~389 ms）在低端机可改为首次 typo 查询时懒构建，或打平成 `Uint32Array` 降内存。
5. pinyin 字符表当前以常量嵌在 `site/build.py`（1,582 字，~12.7 KB 源码）；如后续要独立维护，可移到 `data/sources/pinyin_chars.json` 并在 About 页注明 pinyin-pro（MIT）来源。
6. 拼音别名 token 截断 10 条是体积/覆盖折中，若需完整品牌列表可改存 token→sid 并在客户端懒建 sid→ids。

---

## 7. 复现

```powershell
$py   = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$node = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$env:SITE_OUT='.tmp\dist-search\new'; & $py site\build.py        # 接入后构建
& $node --check .tmp\dist-search\new\assets\app.js
& $node --max-old-space-size=8192 .tmp\dist-search\bench_after.mjs   # 指标 → bench_after.json
& $node --max-old-space-size=8192 .tmp\dist-search\dom_test.mjs      # DOM → dom_results.json
```

证据文件：`.tmp/dist-search/bench_after.json`（指标/逐条 diff/体积）、`.tmp/dist-search/dom_results.json`（断言与对拍）、`.tmp/dist-search/build_before.py`（接入前快照）、`.tmp/dist-search/{old,new}/`（前后构建产物）。
