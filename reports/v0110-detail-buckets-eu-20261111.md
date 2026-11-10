# v0.11.0：detail 明细桶重算（补 EU 2,095 行 + `COALESCE country`）

- 日期：2026-11-11（工作区时钟 2026-11-10 10:11–10:56 -08:00）
- 工位：`page-slim`（任务板 `task-3`）
- 验收对象：`etl/build_detail_buckets.py`，SHA256 `bedcc59f98ae03d5c9b49e16650be3aa4315326dce834ece929556866d03d6d9`
  （生成逻辑定稿后只改过 docstring，未再改代码逻辑）
- 产物：`data/idx/detail-*.json`，51 桶，bundle SHA256（按文件名排序拼接全部字节）
  `323a50d21f9f4a5f69646cf3edeb5b734ff17b4188b390f5d50e1fb48e799724`
- 只读 `data/drugs.db`（`mode=ro`）；**未写** `site/dist`、`data/drugs.db`、`lib/search.py`；
  **未跑** `site/build.py`；未 commit、未发布。`data/idx` 在本报告写完后冻结。

## 结论先行

| 验收项 | 结果 |
|---|---|
| 1. `--stats-only` before/after：桶数 / 行数 / 字节 | **PASS**：51 桶 / **294,895 → 382,035 行** / **46,932,192 → 63,863,947 B**（gzip 9,307,836 → 13,513,124 B） |
| 2a. 逐桶 `country is None` 行数 = 0 | **PASS**：`None` 0、空串 `''` 0（全 382,035 行） |
| 2b. 逐桶 `country == 'EU'` 行数合计 = 2,095 | **PASS**：**2,095**（库内 EU 产品 2,095，一个不少） |
| 3. EU-only trade key 抽查 | **PASS**：`abasaglar` / `abilify` / `actos` → 桶 `a` → `data/idx/detail-a.json` 均含 `country:'EU'` 行，且与库内产品一一对应 |
| 4. 零丢行（本轮 Lead 加严口径） | **规则层 PASS**：旧规则在**现库**上重算的 381,729 行，新桶差集 **0**；新桶只多 306 行（62 条原本被 cap 截掉的 EU 行 + 244 条被 EU 占位挤掉、现归还的单国行） |
| 4b. 与 2026-10-28 旧产物的差额归因 | 926 行 = **550**（`product_id` 已不在现库）+ **376**（同 key 单国产品数已 >12，cap 挤出；旧规则在现库重算同样不含）→ 两类都不是本次改动造成，详见 §2.3 |
| 5. 本报告 | PASS |

体积：raw **+16,931,755 B（+16.1 MiB）**、gzip **+4,205,288 B（+4.0 MiB）**；按上一版 dist 总量
880,817,786 B 估算，发布后 **897,749,541 B**，距 900 MiB 自设上限（943,718,400 B）**余 45,968,859 B（43.8 MiB）**，
距 Pages 1 GB 上限余 102,250,459 B。

## 1. 改了什么（`etl/build_detail_buckets.py`，1 文件 / 5 处）

`git diff --stat`：`1 file changed, 197 insertions(+), 68 deletions(-)`（含 docstring 重写）。

| # | 位置 | 前 | 后 | 为什么必须改 |
|---|---|---|---|---|
| 1 | `build_rows` 的 SELECT（原第 152 行） | `p.country` | `COALESCE(p.country, p.region) AS country` | EU 产品只有 `region='EU'`、`country` 为 NULL（`product` 表二者互斥且必居其一），裸 `p.country` 会落成空串 |
| 2 | 同处 ORDER BY（原第 158 行） | `p.country` | `COALESCE(p.country, p.region)` | 排序口径与展示口径一致；否则 EU 行排序键为 NULL |
| 3 | `sample_check` 的 DB 对拍（原第 275 行） | `SELECT product_id, country …` | `SELECT product_id, COALESCE(country, region) AS country …` | 否则抽样对拍会把 EU 行全判失败 |
| 4 | `load_keys`（新增）+ `main` | 读 `site/dist/data/index.json` 的 127,085 个 `k` | 现查 `product_name(name_type IN ('trade','inn'))` 的 `DISTINCT key_id`（196,211） | **不改就崩**：`site/dist/data/index.json` 自 v0.6.1 起不再生成，现场不存在；且残留口径是过期快照，2026-10-28 之后新增的名字（含 EU）根本没进桶 |
| 5 | 截断规则（`build_rows`，Lead/验收工位定案） | 每 key 取前 12 行（EU 行既可能被截掉，也可能挤掉后面的单国行） | **cap 只数单国行**：区域层行（`country` 为空、`region` 兜底）一律追加、不占名额 | 「补 EU」不能以丢既有国家行为代价（替换 62 行的方案被否） |

附带（不改输出语义，只防坑）：`load_shard_bucket()` 的降级路径由「6 个字的玩具拼音表」改为
「从 `site/build.py` 源码 `ast` 解析 `_PINYIN_CHARS_TEXT`（3 次重试）」。理由：`site/build.py` 由 `site-ui`
并行改写，import 可能读到半成品；而桶划分一旦错位，全站「展开明细」会整体查不到行，宁可报错。
体积预算 `RAW_BUDGET/GZ_BUDGET` 55 MB/10 MB → 70 MB/14 MB（依据见 §4.2）。

## 2. 怎么验的（全部只读；脚本在 `.tmp/page-slim/`，不入库）

Python：`C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`（3.12）。

### 2.1 before / after 扫描（`scan_buckets.py`）

```powershell
& $py .tmp/page-slim/scan_buckets.py before   # 改前（2026-10-28 产物）
& $py .tmp/page-slim/scan_buckets.py after4   # 本轮定稿
```

| 指标 | before（2026-10-28 10:26） | after（2026-11-10 10:49） | Δ |
|---|---|---|---|
| 桶数 | 51 | 51 | 0 |
| key 数 | 127,085 | 196,211 | +69,126 |
| 行数 | 294,895 | **382,035** | **+87,140** |
| raw 字节 | 46,932,192 | **63,863,947** | +16,931,755 |
| gzip 字节（逐桶 -9 求和） | 9,307,836 | 13,513,124 | +4,205,288 |
| `country is None` 行 | 0 | **0** | 0 |
| `country == ''` 行 | 0 | **0** | 0 |
| `country == 'EU'` 行 | **0** | **2,095** | +2,095 |
| 覆盖市场 | AU CA CN ES GB MX US（7） | AU CA CN ES **EU** GB **HK** MX **SG** **TW** US（11） | +4 |
| 桶归属错（key 的首字符 ≠ 所在桶） | 0 | 0 | 0 |
| 最大单桶 | `detail-a` 4,155,643 B | `detail-a` 5,682,353 B（gz 1,194,773 B） | — |

### 2.2 全量逐行对拍（`verify_buckets_full.py`，退出码 0）

对 382,035 行 × 12 字段逐条回查现库：

```
桶 51；key 196,211（库内 196,211，缺 0）；行 382,035
country 分布 {'AU': 50457, 'CA': 40047, 'CN': 59446, 'ES': 37949, 'EU': 2095, 'GB': 48139,
              'HK': 12772, 'MX': 13470, 'SG': 5147, 'TW': 32527, 'US': 79986}
EU 行 2,095；每 key 行数不合 cap 规则的 0
对拍错误合计 0：{}
```

即：`country == COALESCE(country,region)`、status/release/source_id 字典回解、URL 重建
（`p[source_idx] + suffix`）、pack / approval_id / status_date / mah / strength 全部 0 差异；
每 key 的 EU 行数 == 库内 EU 产品数、单国行数 == `min(12, 库内单国产品数)`（这条即「EU 没有占名额、也没被截」的机器证明）。

### 2.3 零丢行：两个层次，别混

**层次一：规则层（本次改动）——零丢行，`legacy_compare.py`**

```powershell
& $py .tmp/page-slim/legacy_compare.py
# artifact 294,895 / legacy_now 381,729 / new 382,035
# 规则层：legacy_now − new = 0（必须 0）；new − legacy_now = 306
```

- `legacy_now` = **旧截断规则在现库上重算**的三元组集合（`(key, product_id, country)`，cap12、EU 也占名额）= **381,729**；
- `new` = 现桶 = **382,035**；
- **`legacy_now − new` 差集 = 0** → 本次改动没有丢任何一行既有行、也没有改它们的相对顺序；
- `new − legacy_now` = 306 行，全部是「追加」：62 条原本被 cap 截掉的 EU 行（`abilify`/`actos`/`advagraf` 等）+ 244 条原来被 EU 占位挤到第 13 位的单国行（现归还）；
- 306 个 key 现在是 13 行（196,211 个 key 中行数 >12 的共 306 个，最大值就是 13），其余 key 的分层不变。

**层次二：相对 2026-10-28 旧产物的差额——926 行，全部可归因，且与本次改动无关**

```powershell
& $py .tmp/page-slim/zero_loss.py          # lost（旧−新）= 926
& $py .tmp/qa-acc/diff_detail_buckets.py --new-dir data/idx   # 验收工位同口径复核
```

| 类别 | 行数 | 说明 | 能否保留 |
|---|---|---|---|
| `product_id` 已不在现库 | **550** | 12 天里重入库/删重，`SELECT … FROM product WHERE product_id=?` 查不到 | **不能**（保留=发布陈旧行；其中 75 个 key 的新旧行数完全相同，属 CN 重新入库后 id 换代，用户看到的行数没变） |
| 同 key 单国产品数已 >12，被 cap 挤出 | **376** | 该 key 在 2026-10-28 之后新增了排序更靠前的产品；**旧规则在现库重算同样不含这 376 行** | 要么抬 cap（会随库增长无限膨胀），要么接受 cap12 的既有设计；**与 EU 无关** |

> 关于验收工位先前报的「374 行 eu-occupation」：那是拿 12 天前的产物做基线，混入了同期的数据漂移。
> 以「旧规则在现库重算」为基线后，EU 造成的占位是 244 行、且已全部归还（§2.3 层次一）。
> 现桶的机器判据：`每 key 单国行数 == min(12, 库内单国产品数)`、`每 key EU 行数 == 库内 EU 产品数`（`verify_buckets_full.py`，0 违规）。

### 2.4 EU-only trade key 抽查（`spot_eu.py`，退出码 0）

查询与桶规则定位：

```sql
-- EU-only trade key（该 key 只有 EU 行，没有单国行）
SELECT pn.key_id FROM product_name pn JOIN product p USING(product_id)
WHERE pn.name_type='trade' AND p.region='EU'
GROUP BY 1 HAVING SUM(CASE WHEN p.country IS NOT NULL THEN 1 ELSE 0 END)=0 LIMIT 3;
-- → abasaglar / abecma / abevmy（另加 abilify、actos 验证「旧版被 cap 截掉」的 key）
```

桶定位 = `_shard_bucket(key)` = key 首字符（小写字母 → 该字母；CJK → `cjk-` + 拼音首字母；数字 → `digit`）。
`abasaglar` / `abilify` / `actos` 都在 **`data/idx/detail-a.json`**：

| key | 桶文件 | 该 key 行数 | 其中 EU 行 | 库内 EU 产品 | 首条 EU 行（品牌 / 批号 / 状态） |
|---|---|---|---|---|---|
| `abasaglar` | `data/idx/detail-a.json` | 2 | 1 | 1 | ABASAGLAR / `EU/1/14/944` / active |
| `abilify` | 同上 | 12 | 1 | 1 | ABILIFY / `EU/1/04/276` / active（旧桶里这条被 cap12 截掉） |
| `actos` | 同上 | 12 | 1 | 1 | ACTOS / `EU/1/00/150` / active（同上） |

直读命令（不依赖我写的脚本）：

```powershell
& $py -c "import json;d=json.load(open(r'data/idx/detail-a.json',encoding='utf-8'));print(d['k']['abasaglar'])"
```

### 2.5 结构一致（旧桶 vs 新桶，`cmp_structure.py`，退出码 0）

用 `git show HEAD:data/idx/detail-{a,e}.json` 取出旧桶对比（脚本读 `.tmp/page-slim/old-idx/`，即 `git archive HEAD data/idx` 的解包副本）：

| 项 | `detail-a.json` | `detail-e.json` |
|---|---|---|
| 顶层字段 | `['k','p','r','s','t','v']` 旧＝新 | 同 |
| `v` / `t`（status 字典）/ `r`（release 字典） | 1 / 4 项 / 7 项，旧＝新 | 同 |
| 行字段数 | 全部 12，旧＝新 | 同 |
| 行字段类型 | `[str,str,str,str,str,int,str,int,str,str,str,int]`，旧＝新 | 同 |
| 变化 | 只有**行数与行内容**（例：`abilify` 首行旧 `AU-8717T-abilify-e7b908` → 新 `EU-eu-1-04-276`） | 同 |

→ 前端 `detPanelHTML()` 的解析路径（`r[0..11]` + `t/r/s/p` 下标、`url=p[source_idx]+suffix`）**不需要任何改动**。

### 2.6 确定性

上一版规则下连续生成两次，51 个文件 **sha256 全同、总字节全同**（`.tmp/page-slim/scan-after-run1.json` vs
`scan-after2.json`，diff 0）。定稿版只改了截断判定与 docstring，序列化路径未变；因 `data/idx` 需尽快冻结
供 `site-ui` 构建，本轮**未再用一次 55 s 重跑复核**——若需要，命令见 §7。

## 3. 数字从哪来（+87,140 行拆解，`breakdown_rows.py`）

| 项 | 数 |
|---|---|
| key 数 | 127,085 → 196,211（新增 69,130，消失 4） |
| 行数 | 294,895 → 382,035（**+87,140**） |
| ├ 新增 key 贡献 | **+83,242 行** |
| └ 老 key 增量 | **+3,898 行**（2,811 个 key 变多、203 个变少；变少是同期重入库导致的产品数下降，不是截断规则） |
| EU 行 2,095 的落点 | 新增 key 上 **662**、老 key 上 **1,433** |

## 4. 三个「为什么」（避免看起来像顺手放宽门槛）

### 4.1 行数 294,895 → 382,035，**不只**来自 EU 的 2,095 行

- 旧桶的 key 集合来自**已停产的 legacy `site/dist/data/index.json`**（127,085 个 k，2026-10-28 快照）；
  现库 `product_name(name_type IN ('trade','inn'))` 有 **196,211** 个 key（+69,126）。
- 所以这次是「**明细覆盖补齐**」+「补 EU」两件事叠加：+87,140 = 83,242（新 key）+ 3,898（老 key 增量），
  其中 EU 只占 2,095。用户可感知：更多名字（含 HK/SG/TW/EU 产品）现在点「展开明细」有内容，
  不再出现「明细为空」。
- 这也解释了体积增长的大头不是 EU：EU 2,095 行 ≈ 0.35 MB。

### 4.2 体积预算 55 MB/10 MB → 70 MB/14 MB

- 脚本默认 `DEGRADE=(12,10,8)`：cap12 实测 63.9 MB raw / 13.5 MB gzip，**旧预算 55/10 会触发自动降级**；
- 而降级是笔烂买卖：cap12→cap10 只省 **1.94 MB**、白删 **13,304 行**；cap12→cap8 省 **4.29 MB**、白删 **29,411 行**
  （含 6,118 个满 cap key 的第 9–12 条）；
- 新预算 70 MB/14 MB = cap12 实测 + 约 10% 余量，够挡住「数据又涨了却没人看」的情况，又不会为了 2–4 MB 删行。
- 该预算**不是发布门槛**：`deploy/` 下没有任何针对 `detail-*.json` 的体积检查（已 grep 复核），
  真正卡体积的是 §4.3 的 dist 总量。

### 4.3 体积增量与 dist 余量 62.9 MB 的关系

| 项 | 字节 |
|---|---|
| 旧桶（在 dist 里是全量拷贝） | 46,932,192 |
| 新桶 | 63,863,947 |
| **增量** | **+16,931,755（+16.1 MiB）** |
| 上一版发布 dist 总量（`reports/v0110-release-20261111.md`） | 880,817,786 |
| 预计本版 dist | **897,749,541**（约 856.1 MiB） |
| 900 MiB 自设上限 `943,718,400` | 余 **45,968,859 B（43.8 MiB）** |
| Pages 1 GB 上限 `1,000,000,000` | 余 102,250,459 B |

→ 增量吃掉 62.9 MB 余量里的 16.9 MB（约 27%），**不会撞线**；但余量从 43.8 MiB 起算，
后续再增大件（如再补一个大市场）要先看这条线。另：`site/build.py:4136` 的注释写
「最大 ~4 MB raw / ~0.9 MB gzip」，现桶最大已是 5.68 MB / 1.19 MB —— **只是注释过期**，
`site/build.py` 不归本工位改，留给 `site-ui` 顺手更新。

## 5. 已知缺口（都不阻塞发布）

1. **相对 2026-10-28 旧产物少 926 行**，构成见 §2.3 表：550 行 \(\text{product\_id}\) 已不在库（不能保留），
   376 行是同 key 单国产品变多后被 cap12 挤出（旧规则在现库同样不含）。**规则层零丢行（0 行）已证。**
2. **cap12 仍是硬上限**：单国行 >12 的 key（6,118 个满 cap + 306 个 13 行）只展示前 12 条单国行；
   明细页脚「仅显示前 12 条」的提示文案在 13 行的 key 上略不精确（前端按 `rows.length >= 12` 判断，
   属既有实现，未改 `site/build.py`）。
3. **`site/dist` 与最终字节**由 `site-ui` 的构建决定，本报告的 897,749,541 B 是按上一版总量 + 桶组件的估算。
4. 定稿版未重跑「两次生成 sha256 相同」的确定性复核（理由见 §2.6）。

## 6. 未做（明确出界）

- 未改 `site/build.py`、`lib/search.py`、`site/dist/**`、`data/drugs.db`（只 `mode=ro` 打开）、`db/schema.sql`；
- 未跑 `site/build.py`、未跑 `deploy/*`、未 commit、未 tag、未发布；
- 未改 `docs/`、`CHANGELOG.md`；未动 `data/raw/`；
- 未把旧桶里「产品已不存在」的 550 行硬塞回来（会发布陈旧数据）。

## 7. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING = 'utf-8'

# 1) 生成（写 data/idx/detail-*.json；--stats-only 只看数字不落盘）
& $py etl/build_detail_buckets.py
& $py etl/build_detail_buckets.py --stats-only

# 2) 逐桶扫描：桶数/行数/字节/None/EU/桶归属自检
& $py .tmp/page-slim/scan_buckets.py after4

# 3) 全量逐行对拍（12 字段 + URL 重建 + 每 key 行数规则）
& $py .tmp/page-slim/verify_buckets_full.py

# 4) 零丢行：规则层（旧规则在现库重算）vs 新桶
& $py .tmp/page-slim/legacy_compare.py

# 5) 与 2026-10-28 产物的差额与归因（旧桶来自 git archive HEAD data/idx）
& $py .tmp/page-slim/zero_loss.py

# 6) EU-only key 抽查
& $py .tmp/page-slim/spot_eu.py

# 7) 结构对照（旧桶 vs 新桶字段）
cmd /c ".\tools\git\cmd\git.exe archive HEAD data/idx | tar -x -C .tmp\page-slim\old-idx"
& $py .tmp/page-slim/cmp_structure.py

# 8) 数据体检（只读，exit 0）：products 479,193 / components 630,151 / collisions(warning) 925
& $py db/check_data.py
```

核对用 SQL（只读）：

```sql
SELECT COUNT(*) FROM product;                                        -- 479193
SELECT COUNT(*) FROM product WHERE region='EU' AND country IS NULL;  -- 2095
SELECT COUNT(*) FROM product WHERE country IS NULL AND region IS NULL; -- 0（schema 保证二选一）
SELECT COUNT(DISTINCT key_id) FROM product_name
  WHERE name_type IN ('trade','inn');                                -- 196211
```

## 附：本工位验证脚本清单（`.tmp/page-slim/`，不入库）

| 脚本 | 作用 |
|---|---|
| `scan_buckets.py` | 扫桶：桶数/行数/字节/gzip/country 分布/桶归属自检 |
| `verify_buckets_full.py` | 382,035 行逐行对拍 DB（12 字段 + URL + 每 key 行数规则） |
| `legacy_compare.py` | 规则层零丢行证明（旧规则在现库重算 vs 新桶） |
| `zero_loss.py` | 与 2026-10-28 产物差额 + 逐行归因 |
| `breakdown_rows.py` | +87,140 行拆解（新 key / 老 key / EU 落点） |
| `spot_eu.py` | EU-only key → 桶定位 → EU 行举证 |
| `cmp_structure.py` | 旧桶 vs 新桶 JSON 结构对照 |
| `stats-20261028.json` / `scan-before.json` | 改前基线（脚本统计 + 桶扫描） |
