# index.json 双写收尾方案（>50 MB 警告）— task-63

> 日期：2026-10-28 · 任务：task-63 · 状态：**只读分析 + 精简 legacy 原型完成**（未改 `site/build.py`、未写 DB、未跑 git/发布）
> 报告口径：`site/dist` 当前构建快照（2026-10-28 10:25 构建，`index.json` 52.93 MB）
> 原型/证据：`.tmp/index-legacy/{slim_*.json, legacy-mini.json, analysis.json, summary.json, final.json}`
> 相关：`reports/index-p1-impl.md`（core）、`reports/index-p2-impl.md`（分片）、`reports/ui-a1-b6-plan.md`

---

## 0. 结论与推荐

**`data/index.json` 是 P1/P2 之后的纯兼容冗余文件：默认路径已不再下载它，只有 `?legacy=1` 与「core.json 加载/解码失败」两条兜底路径会用它。同一份数据已由 `data/idx/core.json` 以列式+字典编码保存。**

推荐 **方案 A（分两步）**：

| 步骤 | 动作 | 收益 |
|---|---|---|
| **v0.5.6（本次可做）** | 停止写 `data/index.json`；`?legacy=1` 改为加载 **core.json + `decodeCore()`**（与默认路径同一份数据）；core 失败时走现有错误/重试 UI（可选再用 legacy-mini 兜底，见 §5-B） | **dist 立减 52.93 MB raw（-13.4%）**；GitHub Pages >50 MB 文件警告消失；publish 推送少 ~9.3 MB gz 等价；构建少写 52.9 MB |
| **v0.5.7（观察一版后）** | 删除 `WRITE_LEGACY_INDEX` 临时开关与死代码 | 代码收敛，无体积变化 |

- 若团队要求「保留一个完全独立的兜底文件」，再采用 **方案 B：精简 legacy 13.05 MB raw / 3.29 MB gz**（<15 MB 目标达成），但只作「core 失败时的降级渲染」，会丢失厂家/家族/组合链接字段（见 §5）。
- **方案 C（直接移除、旧 URL 404）不推荐单独使用**；**方案 D（用上一版 dist 的 index.json）不可行**——GitHub Pages 只服务当前部署，历史构建没有稳定 URL，需另建分支/制品库，复杂度大于收益。

**关键数据**：`index.json` **52.93 MB raw / 9.29 MB gzip**；`core.json` **25.67 MB raw / 6.10 MB gzip**，解码后与 index **127,085 条 × 19 个字段全量对拍 0 差异**（唯一被有意丢弃的 `f` 见 §2.4）。`?legacy=1` 换 core 后，弱网回退传输从 9.29 MB → 6.10 MB（-34%），浏览器解析+解码约 2.28 s → 1.20 s（本机 Python 实测，JS 同量级）。

---

## 1. 现状：谁在用 index.json

| 用途 | 代码位置 | 现状 |
|---|---|---|
| `?legacy=1` 一键回退 | `site/build.py:2793 loadMainIndex()`：`if(LEGACY) return fetchJSON(BASE+'data/index.json')` | 仅 legacy 用户下载 |
| core 加载/解码失败自动回退 | 同函数 `catch`：`fetchJSON(BASE+'data/index.json')` | 正常几乎不触发 |
| **默认检索路径** | `core.json` → 分片 | **不下载 index.json**（P1/P2 后已如此） |
| 构建双写 | `build.py:4811-4815`（写文件 + 注释「发布体积可接受」） | 每次构建写 52.93 MB |
| 发布完整性检查 | `deploy/publish.ps1:114-116` 要求 `data/index.json` 存在且 ≥5 MB；`DEPLOY.md:31` 同步描述 | **移除前必须同步改，否则发布直接失败** |

补充：`build.py:4760` 的 app.js 版本替换链还包含 `.replace("data/index.json", "...?v=...")`（移除后无引用的替换，无害但应删）。更早版本（≤v0.5.0）的 app.js 把 index.json 当主索引加载；当前线上已是 v0.5.5（core+分片），**正常新会话不受影响，仅「浏览器缓存里仍是旧 app.js 的标签页」在刷新前会受影响**（见 §7 风险）。

---

## 2. 体积构成（index.json 52,925,173 B / 9,294,477 B gzip）

### 2.1 字段级原始体积（20 个字段，127,085 条）

| 字段 | 体积 | 占比 | 说明 |
|---|---:|---:|---|
| `ml` | 8.22 MB | 15.54% | 厂家列表（数组，A5 厂家页用） |
| `d` | 4.00 MB | 7.55% | 显示名（与 k 大量只差大小写） |
| `k` | 3.58 MB | 6.76% | 检索键 |
| `x` | 3.38 MB | 6.39% | 英文成分名/展示 |
| `m` | 3.27 MB | 6.17% | 主厂家名 |
| `mu` | 2.70 MB | 5.11% | 厂家页 slug |
| `vs` | 2.48 MB | 4.68% | 盐型/变体 |
| `cu` | 2.18 MB | 4.11% | 组合页 slug |
| `v` | 2.03 MB | 3.83% | 成分 slug |
| `s` | 1.85 MB | 3.49% | 强度数组 |
| `xz` | 1.60 MB | 3.03% | 中文成分名数组（v0.5.5） |
| `f` | 1.14 MB | 2.15% | 剂型（core 编码有意丢弃；见 §2.4） |
| `u` | 0.90 MB | 1.71% | 成分页目标 |
| `c` | 0.81 MB | 1.54% | 国家数组 |
| `l` | 0.80 MB | 1.50% | 链接/类型提示 |
| `gn/mn/g/n` | 0.78 MB | 1.47% | 家族/计数散项 |

→ 前 6 个字段（ml/d/k/x/m/mu）占 ~48%，**厂家与显示名是 index.json 膨胀主因**；core 用「字典列 + d 大小写模式（dp）」把这些压到 25.67 MB。

### 2.2 core.json 与 index.json 的等价性

- `core.json`：25.67 MB raw / **6.10 MB gzip**，`n=127,085`，列式 + 字典编码；
- 本次用 `decodeCore()` 的 Python 等价实现解码**全部 127,085 条**，与 index **逐字段对比 19 个字段（除 f）→ 0 mismatch**（`.tmp/index-legacy/final.json`）；
- 解析+解码耗时：index 直接 `JSON.parse` ≈2.28 s（Python 实测）vs core parse 0.25 s + decode 0.95 s = **1.20 s**。

### 2.3 收益（移除后）

| 指标 | 现状 | 移除后 | 变化 |
|---|---:|---:|---|
| `site/dist` 体积 | 395.39 MB（57,784 files） | **342.47 MB（57,783 files）** | **-52.93 MB（-13.4%）** |
| 最大单文件 | index.json 52.93 MB（>50 MB 触发 GitHub 警告） | core.json 25.67 MB | 警告消失（<50 MB） |
| publish 推送 | 含 index.json | 少 1 个 52.9 MB 文件；git 压缩后约少 **5–9 MB** 传输 | 发布更快 |
| 构建写盘 | 每次 52.9 MB JSON 序列化+写 | 0 | 构建略快 |
| 默认首搜 | 不下载 index | 不变 | **无变化** |
| `?legacy=1` 回退传输 | 9.29 MB gz | 6.10 MB gz（core） | **-34%** |

> 注：dist 395 MB 尚未包含 task-58 的 A1 detail 桶（47 MB）；A1 接入后 dist 会更大，移除 index.json 的收益更明显。

### 2.4 唯一字段差异：`f`（剂型）

`encode_core` 注释（`build.py:4445`）写明「f 客户端 0 处引用，直接丢弃」。但当前 build.py 的 **B7 CSV 导出**使用 `e.f`（`build.py:1968`：`(e.c||[]).join(', '), e.f || '', e.m || '' ...`）→ **core 路径下 CSV 导出的「剂型」列为空**（既有小 bug，与 index.json 无关）。建议收尾时顺手把 `"f"` 加入 `encode_core` 字段列表（`build.py:4496`）与 `CORE_DICT_COLS`（`build.py:4446`）：f 只有 ~9 种字典值，预计 core +0.2–0.3 MB raw / <0.1 MB gz，换来 core 与 index **100% 同构**，legacy 换 core 后语义完全一致。**不修也不影响本次移除**。

---

## 3. 精简 legacy 原型（目标 <15 MB raw）

全部原型在 `.tmp/index-legacy/`（生成脚本 `analyze.py` / `summary.py` / `final.py`）：

| 变体 | 字段 | raw | gzip | 说明 |
|---|---|---:|---:|---|
| 完整 index | 20 字段 | 52.93 MB | 9.29 MB | 现状 |
| plain 最小 UI 集（k,d,x,s,c,l,n,v） | 8 | 21.91 MB | 4.21 MB | 超 15 MB |
| plain 去 d（k,x,s,c,l,n,v） | 7 | 17.28 MB | 2.87 MB | d 由 k 派生（显示名大小写丢失） |
| plain 精简（k,x,s,c,l,n） | 6 | **14.61 MB** | 2.45 MB | <15 MB，但无 d/v/u 链接 |
| **mini-core（k,d,dp,c,x,s,l,n,v,u，同 core 格式）** | 10 列 | **13.05 MB** | **3.29 MB** | ✅ <15 MB；`decodeCore` 可直接解码；保留显示名/成分/强度/国家/链接主字段 |
| k 单列 | 1 | 4.46 MB | 1.15 MB | 仅能当名字列表 |

**推荐原型：`legacy-mini.json` = mini-core 13.05 MB raw / 3.29 MB gzip**（`.tmp/index-legacy/legacy-mini.json`）。它保留 `k,d,dp,c,x,s,l,n,v,u`，丢掉 `ml,mu,m,mn,g,gn,vs,cu,f,xz` → 厂家列表/厂家页/家族/盐型/组合页/剂型/中文名这些字段缺失；若作为长期兜底，前端需要为缺失字段显示 `—`（或只用于「基本搜索可用」的降级提示）。

> 也可把 legacy-mini 进一步压到 9.5 MB（不含 d/dp），但显示名会变全小写；13.05 MB 版更实用。

---

## 4. 方案比较

| 方案 | 额外体积 | 兼容性 | 工作量 | 风险 | 评价 |
|---|---:|---|---|---|---|
| **A. `?legacy=1` → core.json + decodeCore** | **0**（复用已有 core） | 高：core 与 index 除 f 外逐字段等价（已全量验证）；`?legacy=1` 语义从「旧 JSON」变为「非分片全量」，行为与默认全量一致 | 小（~20 行 JS/构建代码 + publish 检查） | 中：legacy 不再独立于 core；旧缓存客户端（≤v0.5.0）可能 404（见 §7） | **推荐** |
| B. 保留精简 legacy（legacy-mini 13.05 MB） | +13.05 MB raw / 3.29 gz | 中：只适合降级渲染（厂家/家族/组合链接缺失） | 中（编码子集 + 前端缺字段兜底 + 回退链） | 低-中 | 可作为 A 的「core 失败」二级兜底；非必需 |
| C. 完全移除、失败提示 | 0 | 低：legacy 直接不可用；旧客户端回退路径 404 | 最小 | 高（失去一键回退） | 不单独推荐 |
| D. 用上一版 dist 的 index.json | 取决于保留策略 | 低：Pages 无历史 URL；需另存分支/对象存储 | 大 | 高（多一条发布链） | 不推荐 |

---

## 5. 分步 patch（只给方案，本任务未改任何文件）

### Step 0（前置，可并入 v0.5.6）：修 core 的 `f`（可选但建议）
- `site/build.py:4496` 的 `for f in (...)` 元组加入 `"f"`；`site/build.py:4446 CORE_DICT_COLS` 加 `"f"`（或有序列化）→ core 增加 ~0.2–0.3 MB raw；B7 CSV 导出剂型列恢复。

### Step 1（v0.5.6）：默认停写 index.json，legacy 改 core
| # | 文件/位置 | 改动 |
|---|---|---|
| 1.1 | `site/build.py:4811-4813` | 用开关包裹写文件：`WRITE_LEGACY_INDEX = os.environ.get("WRITE_LEGACY_INDEX") == "1"`；仅当为真时写 `(OUT/'data'/'index.json')`；默认**不写** |
| 1.2 | `site/build.py:4814-4815`、`4913` | 更新注释与构建日志（`index.json` 行改为条件打印或标「deprecated」） |
| 1.3 | `site/build.py:4760` | 删除 app.js 版本替换链里的 `.replace("data/index.json", ...)`（无引用后纯冗余） |
| 1.4 | `site/build.py:2793-2799 loadMainIndex()` | `if(LEGACY) return fetchJSON(BASE+'data/idx/core.json').then(decodeCore)`；默认路径 catch 改为：先试 `data/idx/legacy-mini.json`（若 Step 2 做了方案 B）再试 core 错误提示；不再引用 `data/index.json` |
| 1.5 | `deploy/publish.ps1:11,114-116` | 完整性检查改为 `data/idx/core.json` 存在且 ≥5 MB（25.67 MB 满足）；若保留 `WRITE_LEGACY_INDEX=1` 过渡，则「index.json 存在则检查 ≥5 MB，不存在则检查 core.json」 |
| 1.6 | `DEPLOY.md:31` | 同步「data/idx/core.json（≥5 MB）」 |
| 1.7 | `CHANGELOG.md` v0.5.6 节 + `README`（若有发布体积描述） | 写「移除 index.json 双写，legacy 走 core；dist −52.9 MB；?legacy=1 仍可用」 |

### Step 2（可选，方案 B 二级兜底；非必需）
- 构建时用 `encode_core` 的列子集另写 `data/idx/legacy-mini.json`（13.05 MB，复用 §3 编码）；`loadMainIndex` 的 catch 用它；前端对缺失的 `m/mu/ml/g/gn/vs/cu/f/xz` 做 `—` 兜底。只在「core 损坏且要保住基本搜索」时值得做。

### Step 3（v0.5.7）：清理
- 删除 `WRITE_LEGACY_INDEX` 开关与 `legacy-mini` 相关死代码（若 Step 2 未采用则无）；`publish.ps1` 去掉 index.json 兼容分支。

### 验收清单
- `site/build.py` 构建到 `== done ==`；`site/dist/data/index.json` **不存在**；dist 体积 ≈342.5 MB（-52.9 MB）；
- `?legacy=1` 正常出结果（DOM/手工抽 3 条），`?legacy=1&q=Lipitor` 与默认路径结果一致；
- 模拟 core 404（临时改名）→ 默认路径显示错误/重试（或 legacy-mini 降级），不白屏；
- `deploy/publish.ps1 -DryRun` 通过（若 Gate 已改）；`publish.ps1` 完整性检查项更新；
- 首搜体积回归不变（index 不在默认路径）；GitHub Pages 推送无 >50 MB 警告。

---

## 6. 回滚

- 方案 A 是**单文件补丁**：`git revert`（或恢复 `build.py` 的 3 处改动 + `publish.ps1` 检查），重跑 `site/build.py` 即恢复双写；index.json 内容无数据变化。
- 过渡期可保留环境变量：本地/紧急发布用 `$env:WRITE_LEGACY_INDEX='1'; python site/build.py` 临时恢复 index.json；`publish.ps1` 的兼容分支也接受它。
- 不涉及 DB/数据变更，回滚无数据风险。

---

## 7. 风险清单

| 风险 | 说明 | 缓解 |
|---|---|---|
| **旧缓存客户端** | ≤v0.5.0 的 app.js 把 `data/index.json` 当主索引；移除后这些标签页刷新前搜索会 404 | 影响窗口：仅有旧标签页的用户；新会话拿新 HTML/app.js 走 core。若要零风险，可先发一版「默认仍写 index、客户端已不依赖它」，再下一版移除（多一周 50 MB 警告） |
| **发布 Gate 未同步** | `publish.ps1` 硬性要求 index.json ≥5 MB，先删文件后改 Gate 会导致发布失败 | 同一 commit 改 Gate；`-DryRun` 先验证 |
| **legacy 单点依赖 core** | 以前 legacy 可在 core 坏时独立救场；改后两者共用 core 文件/解码代码 | 可加方案 B 的 13 MB legacy-mini 兜底；或接受（core 损坏时默认路径本身也重伤） |
| **core 缺 `f`（既有）** | B7 CSV 导出剂型列在 core 路径为空；legacy 换 core 后同上 | Step 0 顺手给 core 加 `f`（+0.2–0.3 MB） |
| **后端未发版前的中间状态** | 若只改代码未重发，线上仍有 index.json；无影响 | 移除随下一次发布生效 |
| **CDN/浏览器缓存** | `data/index.json?v=` 旧 URL 可能仍被缓存，不构成问题（新 app.js 不再请求） | 无需额外处理 |
| **A1 detail 接入后 dist 变大** | task-58 桶约 47 MB 尚未进 dist；移除 index 后总盘更可控 | 按计划接入时保持预算监控 |

---

## 8. 证据 / 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py .tmp\index-legacy\analyze.py   # 字段体积、core 等价性、slim 变体
& $py .tmp\index-legacy\summary.py   # 字段表 + plain 精简组合
& $py .tmp\index-legacy\final.py     # 全量等价性(0 mismatch)、加载耗时、legacy-mini 13.05MB
```

- `.tmp/index-legacy/analysis.json` / `summary.json` / `final.json`：上述全部原始数字；
- `.tmp/index-legacy/legacy-mini.json`（13.05 MB）：可被现有 `decodeCore()` 解码的精简兜底原型；
- 其他 slim 原型（`slim_*.json`、`mini_core.json`）保留供对比；
- 本报告未改 `site/build.py`、`data/drugs.db`，未跑 git/发布；`data/index.json`/`core.json` 仅只读。
- 快照口径：dist 构建于 2026-10-28 10:25（index 52,925,173 B；core 25,668,996 B；dist 57,784 files / 395.39 MB）。
