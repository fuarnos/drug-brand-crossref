# 三语检索评测集扩容报告（72 → 320 例）

日期：2026-10-27 ・ 任务：task-37 ・ 站点版本：v0.3.5
产物：`tests/trilingual/gen_cases.py`、`tests/trilingual/cases_v2.json`（320 例）、
`tests/trilingual/run_cases_v2.py`、本报告；自检/基线明细在 `.tmp/search-eval/`。
本轮**未改** `tests/trilingual/run_tests.py` 的通过门槛，未写 `data/drugs.db`、未跑 build/git/发布。

---

## 1. 摘要

| 指标 | 结果 | 设计门槛（who-inn-merge §6.5） |
|---|---|---|
| 用例总数 | **320**（8 类，配额全满） | ≥320 ✅ |
| seed / DB 绑定 | `20261027` / DB sha256 `31bcae91…`（快照，见 §2） | 固定 seed ✅ |
| 期望策略 | must_hit 225 ・ gap 55 ・ must_empty 40 | — |
| **must_hit Top-5** | **218/225 = 96.9%** | ≥95% ✅ |
| must_hit Top-1 | 200/225 = 88.9% | 记录 |
| **must_empty（零结果）** | **40/40 = 100%**；误命中 0 | 100% ✅ |
| gap（不计入通过率） | 55 例；「意外命中」15 | 记录 |
| 综合通过率（Top5+empty） | **258/265 = 97.4%** | — |
| 320 例基线耗时 | **214.7s ≈ 3.6 min**（`--jobs 6` 并行） | 3–4 min ✅ |
| 期望独立复核 | 320/320 通过（SQL 重新推导，0 不一致；零结果 40/40 重验） | — |

分类基线：

| 类别 | n | Top-1 | Top-5 | Top-5% | empty | 误命中 | gap | gap 意外命中 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| en_typo（英文错拼） | 45 | 35 | 41 | 91.1% | — | — | — | — |
| es_typo（西语错拼） | 30 | 18 | 27 | 90.0% | — | — | — | — |
| zh_char_typo（中文错字） | 25 | 24 | 25 | 100% | — | — | — | — |
| pinyin（拼音/首字母） | 40 | 0 | 0 | 0% | — | — | 40 | 0 |
| jianfan（简繁） | 30 | 30 | 30 | 100% | — | — | — | — |
| combo（复方） | 55 | 40 | 40 | 100% | — | — | 15 | 15 |
| salt（盐型） | 55 | 53 | 55 | 100% | — | — | — | — |
| zero_result（零结果） | 40 | — | — | — | 40 | 0 | — | — |

**结论**：除「拼音」类（py 侧索引只在站点客户端，Python `lib/search.py` 尚无拼音层）外，
其余七类基线均达标（≥90%/100%）；7 条 must_hit 未命中主要是**超长/非常规商品名**与
**fuzzy 排序**问题（§5），不是期望值错误（§4 已逐条 SQL 复核）。

---

## 2. 快照与反循环论证

- 生成器**只读** DB（`mode=ro`），并记录 DB 文件 sha256/size/mtime 到 `cases_v2.json.meta`；
  本轮绑定快照 sha256 **`31bcae91abc21796b39aa83f9ce2e8458c4bb90c515af41b48c09b0eefd6b313`**
  （`.tmp/search-eval/eval-db-snapshot.db`，由 sqlite backup API 原子复制；规避并行 agent 写库锁）。
- **期望不来自检索输出**：`gen_cases.py` 不 import `lib/search.py`；期望全部来自
  `product_component → variant → substance`、`name_key/name_variant`、`variant.salt`、
  WHO 表（`data/who_inn_names.csv`）与规则表（`_T2S`、拼音字表、人工混淆表）。
- 生成后再用 `.tmp/search-eval/verify_cases.py` **独立 SQL 重推**一次期望（不读生成器内存），
  结果 320/320 一致：数据库类 270 条全 ok，WHO 派生 10 条 ok，零结果 40 条 SQL 重验 ok。
- 换库流程：新快照 → `gen_cases.py --db <snapshot>` → `verify_cases.py` → 重跑基线；
  `meta.db.sha256` 不一致即视为 data drift（本轮运行期间线上库正被其他 agent 写入，故用快照）。

---

## 3. 八类生成规则（实现与配额）

| # | 类别 | n | 查询来源 | 构造算法 | 期望来源 | policy |
|---|---|---:|---|---|---|---|
| 1 | en_typo | 45 | `name_key` latin 商品名（trade 优先） | 1 次编辑：换位 40%/QWERTY 邻键 30%/删 20%/插 10%；difflib ratio≥0.78 才收录 | 该 name_key 下 active 产品的成分集合 | must_hit |
| 2 | es_typo | 30 | ES/MX 拉丁名 + `who_inn_names.csv` 西语名 | 同上；30% 去重音符子类；20 条库内 + 10 条 WHO（en 名反查 DB 成分） | 同上 / WHO es↔en + DB `inn_en` | must_hit |
| 3 | zh_char_typo | 25 | 中文 `name_key`（长度≥4） | 44 对人工形近/音近混淆表替换 1 字（氨/胺、唑/坐、嗪/秦、孢/胞、钠/纳…） | 该 key 的成分集合 | must_hit |
| 4 | pinyin | 40 | 中文名（2–8 字，字全部在拼音表中） | 全拼 20 条（`yumeifensanpian`）+ 首字母 20 条（`ymfsp`） | 该 key 的成分集合 | **gap**（Python 检索层无拼音索引） |
| 5 | jianfan | 30 | 中文名（含 `_T2S` 覆盖字） | 用 `_T2S` 反表简体→繁体构造查询（鹽酸/嗎丁啉/鈉…） | 该 key 的成分集合 | must_hit |
| 6 | combo | 55 | ≥2 成分、成分集合稳定的 key | 40 条商品名原样；15 条成分英文名 `+` 拼接（标记 gap） | `product_component` 全集合 | must_hit(40)/gap(15) |
| 7 | salt | 55 | `variant.salt<>''` 的 active 产品 | 40 条盐型商品名原样；15 条 `inn_en + salt` 且该串在 `name_key` 精确存在 | 碱基 substance | must_hit |
| 8 | zero_result | 40 | 生成器 + SQL 负校验 | 随机拉丁 7–12/5–6+数字、随机 CJK 2–4、非药词；**必须**无 name_key（精确/子串）、无 alias、无 confusable、**无 fuzzy≥0.75** 才收录 | 无 | must_empty |

分层：每 key 取 `name_key` 的规范名/原始名；语言按查询语言标（en/es/zh）；单 key 期望要求
其 active 产品成分集合一致（避免同名不同成分的歧义）。provenance 记录
`source/row_ids(key_id 或 WHO inn_number)/detail/seed/db_sha256`。

样例（每类 2 条）：

| 类别 | 查询 | 期望 |
|---|---|---|
| en_typo | `MODOIDAL`（原 Modiodal） | modafinil |
| en_typo | `DAlOSAR`（原 daposar） | dapagliflozin |
| es_typo | `THEO-DhR`（原 theo dur） | theophylline |
| es_typo | `teplizumabt`（WHO en teplizumab） | teplizumab |
| zh_char_typo | `盐酸吡格列铜胶囊`（原 …酮…） | pioglitazone |
| zh_char_typo | `注射用头孢他啶阿维巴坦纳`（原 …钠） | ceftazidime（+阿维巴坦） |
| pinyin | `yumeifensanpian` / `ymfsp` | cn-261ad64dfb（愈美分散片） |
| jianfan | `註射用鹽酸格拉司琼` | granisetron |
| combo | `Prilocaine 60mg/2ml / Felypressin … cartridges` | felypressin+prilocaine |
| salt | `Nubain 10mg/1ml …`（盐酸纳布啡） | nalbuphine |
| zero_result | `yoqgjegnrqkv` / `对平` | 无（SQL 验证） |

---

## 4. SQL 二次验证（写入报告的可复核项）

`gen_cases.py` 对零结果类逐条执行：
1. `name_key.norm/compact` 精确命中 → 拒绝；
2. 中文：`name_key.norm` / `name_variant.raw` / `alias_all.alias` 的 `LIKE %q%` 子串命中 → 拒绝；
   拉丁（len≥4）：`norm/compact/raw` 子串命中 → 拒绝；
3. `alias_all.alias_norm`、`confusable_pair.norm_a/b` 精确命中 → 拒绝；
4. **fuzzy 复核**：拉丁（len≥4）对 135k 拉丁 name_key 做 `ratio≥0.75` 检查（与
   `lib/search.py:FUZZY_MIN` 同阈值）→ 命中则拒绝（本轮因此淘汰了 `foo bar` 等会误命中的候选）。

独立复核脚本 `.tmp/search-eval/verify_cases.py`：
- 按 provenance `key_id` 重新 SQL 推导期望成分（要求该 key 产品成分集合一致），
  en/es/zh/pinyin/jianfan/combo/salt 共 280 条全部一致；
- WHO 派生 10 条：按 `inn_number` 取 `inn_es/inn_en`，用 DB `inn_en` 反查 substance，全部一致；
- 零结果 40 条重验全部仍为「无命中」。
- 输出 `.tmp/search-eval/verify.json`：`bad=[]`、`zero_sql_ok=40`、`who_ok=10`。

---

## 5. 基线结果与未命中分析

基线明细：`.tmp/search-eval/baseline.json`（逐条 rank/top1/cards/note/seconds）。
运行命令：`python tests/trilingual/run_cases_v2.py --db <snapshot> --json ... --jobs 6`。

7 条 must_hit 未命中（均为 Top-5 未含全部期望）：

| 类别 | 查询 | 期望 | 现象 |
|---|---|---|---|
| en_typo | `Bach Original Flower Reedies Aspen` | Populus Tremula Flowering Top | fuzzy 命中了同系列 `…Whole`，Top-1 是相近但不同产品 |
| en_typo | `CAMBINRE` | Colistimethate | 结果里只有氧化物类（fuzzy 噪声），未命中目标 |
| en_typo | `sesame 50micrograms ml for skin prick tets` | Generic Sesame … Test | 命中同族 `Generic Pea … Test`（超长名 + 数字） |
| en_typo | `healon for lre filled syringes` | Sodium Hyaluronate | 命中了玻璃酸钠另一产品/品牌名排序 |
| es_typo | `PAROXETINA KERN PHARiMA` | Paroxetine | fuzzy 排序把 Ebastine 等排前 |
| es_typo | `teplizumabt` | Teplizumab | fuzzy 命中了 atezolizumab（前缀/相似度接近） |
| es_typo | `arsburicasa` | Rasburicase | 仅 1 张卡且为 `Rasburicasa`（西语拼写变体，非目标 INN 成分） |

分析：① 生成器允许**超长/带规格的商品名**（部分来自真实 `name_variant`），这类查询本身的
fuzzy 扩展噪声大；② Top-5 判定要求「全部期望成分出现在同一张卡」，对复方/盐型更严格；
③ 7/225 = 3.1% 属真实基线缺口，可作为下一轮「fuzzy 排序 / 长名截断 / gap 词表」改造目标。
Top-1 88.9% 与 Top-5 96.9% 的差距也集中在这些样例。

**gap 类**（55）：拼音 40 条 0 命中（真实缺口：`lib/search.py` 无拼音层，客户端才有
`data/idx/pinyin.json` 懒加载）；combo 成分拼接 15 条**意外全部命中**（这些拼接串恰好等于
库里已有的复方 name_key）→ 说明「成分拼接」不是当前缺口，建议 v2.1 改归 must_hit，
真正的复方缺口是「用户只写部分成分」的查询（当前未纳入评测）。

零结果 40/40 通过（无误命中）；上一版曾有 1 条 `foo bar` 因 fuzzy≥0.75 误命中，
已通过在生成器加入 fuzzy 负校验修复。

---

## 6. 仍缺的素材 / 依赖

| 缺口 | 影响 | 建议 |
|---|---|---|
| Python 检索层无拼音索引（pinyin 仅站点客户端 `site/dist/data/idx/pinyin.json` + `site/build.py` 字表） | 拼音 40 例全 gap | 把客户端拼音 token（`j:`/`i:`）逻辑移植到 `lib/search.py`，或用 `data/idx/pinyin.json` 在服务端建映射；改造后 baseline 转 must_hit |
| 无西语错拼专用表 | es_typo 仅 20 条库内 + 10 条 WHO（全量 WHO 1,415 条西语名可扩到 100+） | 从 `data/who_inn_names.csv` 全量派生，或引入西语常见拼写错误表（人工/公开表） |
| 简繁只有 `_T2S` 90 对 | jianfan 只能覆盖这 90 字（本轮 30 例全命中） | OpenCC `TSCharacters.txt`（Apache-2.0）完整表；许可写入 `data/sources/README.md` |
| 中文错字只有人工 44 对 | zh_char_typo 的覆盖面有限 | 建 `data/sources/zh_char_confusions.csv`（人工审）并扩到 100+ 对 |
| 超长/带规格产品名噪声 | en/es 错拼 3-4 条 miss 来自 long-name fuzzy | 生成器过滤带剂量/规格/长品牌串（v2.1），或改进长名检索 |
| DB 正被其他 agent 并行写入 | 用例绑定快照 sha；线上库会漂移 | 换库必须重生成（`--db <snapshot>`）+ 重跑 verify + 基线；报告/fixture 记录 sha |

本轮**未安装** `pypinyin` / OpenCC：拼音字表来自 `site/build.py` 内嵌 `_PINYIN_CHARS_TEXT`
（1,582 字，构建产物之一），简繁用 `etl/normalize_name.py` 的 `_T2S`——满足生成需要。

---

## 7. 接 CI 的方式（不改现有门槛）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# 一次性/换库时：快照 + 生成 + 自检
& $py -c "import sqlite3; s=sqlite3.connect('file:data/drugs.db?mode=ro',uri=True); d=sqlite3.connect('.tmp/search-eval/eval-db-snapshot.db'); s.backup(d)"
& $py tests/trilingual/gen_cases.py --db .tmp/search-eval/eval-db-snapshot.db
& $py .tmp/search-eval/verify_cases.py

# CI 每次跑基线（约 3.6 分钟，6 进程）：
& $py tests/trilingual/run_cases_v2.py --db .tmp/search-eval/eval-db-snapshot.db `
      --json .tmp/search-eval/baseline.json --jobs 6
```

- **推荐卡口**（可直接从 baseline.json 断言）：`must_hit Top5 ≥ 0.95`、
  `must_empty 误命中 = 0`、单类 Top5 ≥ 0.90（pinyin lag 除外，按 gap 记录趋势）；
- 现有 `run_tests.py`（72 例）保持不动、仍可单独跑；扩展集是独立可选 job，
  `run_cases_v2.py` 当前始终退出 0（记录基线用），建议加 `--strict` 后再进 CI 卡口；
- 运行时间：单进程约 15+ min（135k name_key 的 fuzzy 扫描），**CI 必须 `--jobs`**
  （实测 6 进程 214.7s）；按类拆子集跑可进一步缩短。

---

## 8. 文件与复现

| 文件 | 内容 |
|---|---|
| `tests/trilingual/gen_cases.py` | 生成器（seed=20261027；`--db/--seed/--dry-run`；只读 DB；不 import 检索层） |
| `tests/trilingual/cases_v2.json` | 320 例 + meta（seed、DB sha256/size/mtime、分类计数、policies、shortages=[]、来源） |
| `tests/trilingual/run_cases_v2.py` | minimal runner（`--cases/--db/--json/--category/--limit/--quiet/--jobs`；只读；复用 `lib/search.py`） |
| `.tmp/search-eval/eval-db-snapshot.db` | 评测绑定的 DB 快照（sha256 `31bcae91…`） |
| `.tmp/search-eval/verify_cases.py` / `verify.json` | 期望独立 SQL 复核（320/320 ok，bad=[]） |
| `.tmp/search-eval/baseline.json` | 逐条基线（rank/top1/cards/note/seconds）+ summary |
| `.tmp/search-eval/patch_gen.py` | 生成器补丁记录（可选，供追溯） |

复现：

```powershell
& $py tests/trilingual/gen_cases.py --db .tmp/search-eval/eval-db-snapshot.db
& $py .tmp/search-eval/verify_cases.py
& $py tests/trilingual/run_cases_v2.py --db .tmp/search-eval/eval-db-snapshot.db --json .tmp/search-eval/baseline.json --jobs 6
```

---

## 9. 后续建议（下一步优先级）

1. **移植拼音层到 `lib/search.py`**（客户端已有完整 `pinyin.json`/字表）：pinyin 40 例从 gap 转
   must_hit，预计整集通过率 +15pp（258/265 → 约 298/305）。
2. **v2.1 规则微调**：combo 成分拼接 15 条改 must_hit；过滤超长/带规格商品名；es_typo 扩
   WHO 全量 1,415 西语名；zh 错字表扩到 100 对；简繁换 OpenCC 全表。
3. **fuzzy 排序改进**（长名、多结果时 Top-5 排序）：针对 §5 的 7 条 miss 做回归。
4. **人工抽检 10%（32 例）**：建议从 baseline.json 按类分层抽 10%，核对「查询→期望」是否符合
   用户真实错法；本报告已用独立 SQL 复核全部 320 条期望关系（自动层），人工语义抽检仍建议做一次后冻结 v2.0。
5. **接 CI**：把 `run_cases_v2.py --jobs 6` 作为可选 job（快照方式），阈值见 §7；换库时重生成。
