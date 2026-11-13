# T10：规格 / 剂型 / 复方分组与显示准确性（task-5，v0.11.6）

> 工位：**site-ui** ｜ 时间：2026-11-14（北京谷段）｜ 任务：`task-5`（T10，方案 `reports/2026-11-14-t10-grouping-plan.md`，清单 T15）
> 状态：**实现 + 自验完成**。未 commit、未发布、未写 `site/dist`、未改 `data/drugs.db`、未改 `collision` 视图。
> 写作用域：`site/build.py`、`tests/test_spec_grouping.py`、本报告；构建产物在 `.tmp/dist-v0116`（停在 `== done ==`，供 atc4-ui / phaseb-data 对照）。

## 0. 结论先行

1. **分组键补上「完整成分组合」**：`spec = (规格, 剂型, 释放, others_sig)`，`others_sig` = 除本页成分外的「成分@各自含量」签名（plan §2.1）。单方产品 `others_sig=""` → 纯单方页与旧 key 逐字等价。
2. **`960 mg/30 mL` 不再缩成 `960 mg`**：全站规格串收敛到 `_spec_text()`（成分页 / 品牌页成分卡 / 品牌页明细表 / 搜索索引四处；第 5 处明细桶在 `etl/`，记 T10b）。结果页那一行现在是 **`片剂 500 mg · 胶囊 500 mg · 液体 960 mg/30 mL`**（改前 `500 mg / 960 mg` + 一个 `片剂` 标签）。
3. **成分页露出浓度行**：acetaminophen 页 `960 mg/30 mL` 出现次数 **0 → 1**（改前被「每国 12 行 + 每剂型 10 chip」裁掉），且写在折叠摘要里（摘要常显），展开后每剂型还各带一个浓度规格。
4. **单方 / 复方二分**：acetaminophen 页 11 个国家块里 **10 个「仅含此成分」+ 8 个「含此成分的复方」**（只有两侧都非空的块才出标题），复方行列出全部活性成分**与各自含量**（例：`Acetaminophen 对乙酰氨基酚 250 mg + Amantadine 盐酸金刚烷胺 100 mg`）；「不可互换」提示保留（`drug.notice` 原文未改）。
5. **精度归整**：`_snap_strength()`（`v≥1 ∧ |偏差|≤0.01 ∧ 相对≤2e-5`）→ 41 个 `500.x` 归整成 `500 mg`；`0.00025` / `469.01` / `100.008` / `666666.666667` 一个都不动（单测锁定）。数据层零改动。
6. **名称-规格冲突只做机制、默认关闭**（Lead 2026-11-14 定的范围）：`matrix.spec_conflict` 徽标 + `data-spec-conflict` + `data/sources/name_spec_conflict_20261114.csv` 开关（`SPEC_CONFLICT=1` 才加载）。构建日志实测 `spec conflict: off (mechanism only, T15 list not enabled)`，页面**一条徽标都没有**。
7. **`core.json` raw 45.24 MB → 46.30 MB（+1.00 MiB，44.15 MiB）**，≤48 MB 护栏；gzip 9.69 → 9.82 MiB（2.5–12 MB 区间）。体积换法：`fs` 用紧凑串 + 只在多剂型时写 + 组/规格各自封顶（见 §3）。
8. **CI / 测试 / i18n**：`ci_checks.py --fast --dist .tmp/dist-v0116` **PASS 8 / FAIL 0 / SKIP 4**；新增单测 `tests/test_spec_grouping.py` **16 项全绿**；`deploy/i18n_check.py` **FAIL 0 / WARN 2（未新增）/ INFO 24**，键数 572 → 577（新增 5 个键四语 + fr）。

## 1. 改了什么（`site/build.py`）

| # | 位置（grep 锚点） | 改动 |
|---|---|---|
| 1 | `def _snap_strength`（新，`_normalized_strength` 之前） | 显示层窄口归整（plan §4.1）；`_normalized_strength` 两条分支都套用它，**只在真的归整时**改写法（未归整的保持原千分位格式，避免顺手改 12 万页数字写法） |
| 2 | `def _spec_text` / `def _spec_kind` / `def _fs_pack`（新，`_strength_origin_html` 之后） | 全站唯一规格串（含 per_volume）；per_volume 单位分类；索引里的紧凑 `剂型\|规格;规格` 打包 |
| 3 | `def build_drug_pages` | ① 预扫 `comps[pid]`（650,358 行，一次）；② key 加 `others_sig`；③ 排序按 plan §2.2 **末位补全序** `(form, rel, others_sig)`；④ 矩阵行补 `data-others / data-spec-kind / data-combo` 与复方成分行；⑤ `_spec_num` 提到模块级（品牌页共用） |
| 4 | `def _drug_list_html` | 重构成「每国 × 段」：`_render_segment()` 产出 mono/combo 两段（段标题 `drug.mono_section` / `drug.combo_section`，仅两侧都非空才出），复方段用 `COMBO_ROWS_PER_BLOCK=5`；折叠摘要写出该段**所有**浓度型规格；每剂型折叠组保底 1 个浓度规格 |
| 5 | `def collect_name_data` / `def build_name_pages` | 成分卡按「剂型 → 规格」分桶；多剂型时标签换 `name.form_spec` 并写 `片剂 500 mg；液体 960 mg/30 mL`（plan §7-C） |
| 6 | `def _name_product_table`（品牌页单包装明细） | SQL 补 per_volume 两列，规格走 `_spec_text` |
| 7 | `def load_index` | SQL 补 per_volume；`s` 用 `_spec_text`；新增 `fs`（≤3 组 × 每组 ≤3 个，仅多剂型）；`f` 多剂型时写 `"multi"` |
| 8 | `CORE_FIELDS` / `CORE_ARRAY_COLS` | 加 `fs`（构建期守卫：漏列直接中止） |
| 9 | JS `specPairsOf` / `formLabelOf` / `flatRowHTML` / `brandRowHTML` / `identityCardHTML` / `brandHTML` | 按 `fs` 出「剂型 + 规格」对；`f==='multi'` → `matrix.multi_form`（「多剂型」）；旧索引无 `fs` 时回退 `s` + `f` |
| 10 | `load_spec_conflicts` / `_spec_conflict_badge`（新） | 名称-规格冲突：默认关闭；开关 + 清单在位才加载/渲染；只加标记，不改值/分组/排序 |
| 11 | `UI_I18N`（en/es/zh/zh-Hant）+ `FR_I18N` | 5 个新键：`matrix.multi_form` / `drug.mono_section` / `drug.combo_section` / `matrix.spec_conflict` / `name.form_spec` |
| 12 | CSS | `.card h2 .name-zh,.famcmp .name-zh,.m-combo .name-zh`（T12 起的中文成分名样式扩到复方行） |

**没动**：`_family_block`（T12 范围）、`collision` 视图、`etl/build_detail_buckets.py`（明细桶仍是 `960 mg 30 mL` 空格写法，记 T10b）、`.c-dose/.form-tag/.mkrow/.mkblock/main .card/.m-orig/.nolang-badge/.formchips` 类名（atc4-ui 的守卫依赖）。

## 2. 验收证据

### 2.1 构建 / CI / 测试

```
& $py site/build.py（SITE_OUT=.tmp/dist-v0116）→ == done ==
  drug pages 12,438 / name pages 80,885 / combo 6,896 / maker 15,213
  ingredient zh: 3,103 · spec conflict: off (mechanism only, T15 list not enabled)
  core.json 46.3 MB · total 992.3 MB

& $py deploy/ci_checks.py --fast --dist .tmp/dist-v0116
  12 项：PASS 8 / FAIL 0 / SKIP 4（12.4s）

& $py -m unittest tests.test_spec_grouping -v    →  Ran 16 tests, OK
& $py deploy/i18n_check.py                       →  FAIL 0 / WARN 2 / INFO 24（577 键 × 5 语）
```

### 2.2 三个复现案例 before / after

**(a) 结果页 `/?q=Tylenol`（客户端渲染，浏览器实测 zh）**

| | 剂量格 |
|---|---|
| before（v0.11.5） | `500 mg / 960 mg` + `<span class="form-tag">片剂</span>`（一个「片剂」代表整行） |
| after（v0.11.6） | `片剂 500 mg · 胶囊 500 mg · 液体 960 mg/30 mL`，DOM：`<span class="form-tag">片剂</span> 500 mg · <span class="form-tag">胶囊</span> 500 mg · <span class="form-tag">液体</span> 960 mg/30 mL` |

同页 `document.body.innerText` 命中 `960 mg/30 mL` = **true**（改前 false）；候选集语义句仍在（`结果永远是候选集` = true）。

**(b) `/name/tylenol-extra-strength.html`（品牌页成分卡）**

| | 成分卡 meta |
|---|---|
| before | `Form: capsule、liquid、powder、tablet · Strength: 500 mg、960 mg`（规格跨剂型拼一条） |
| after（zh） | `剂型: 胶囊、液体、粉末、片剂 · 规格（按剂型）: 片剂 500 mg；胶囊 500 mg；液体 960 mg/30 mL；粉末 500 mg/950 mg` |

页面字节 3,403 → 6,023 B（含 T12 的族表），`960 mg/30 mL` 出现 1 次；`name.form_spec` 标签在位；索引里该 key：`f="multi"`、`fs=["tablet|500 mg","capsule|500 mg","liquid|960 mg/30 mL"]`、`s` 含 `960 mg/30 mL`。

**(c) `/drug/acetaminophen.html`（成分页）**

| 项 | before | after |
|---|---|---|
| 页面字节 | 159,971 | **238,208（232.6 KiB，1.489×，≤240 KiB）** |
| `960 mg/30 mL` | **0 次** | **3 次**（折叠摘要里常显 + 展开后每剂型各带一个浓度规格；浏览器 `main.innerText` 命中 = true） |
| 段标题 | 无 | 每国「仅含此成分 / 含此成分的复方」，acetaminophen 页 **10 / 8** 段（两侧都非空才出；第 1 个国家块只有单方 → 只有 1 个标题） |
| `.mkblock` / `.mkrow` | 11 / 110 | 11 / 150 |
| 复方行 | 混在单方剂量组里，只有名字 | `data-combo="1"` 行 40 条，行内 `Acetaminophen 对乙酰氨基酚 250 mg + Amantadine 盐酸金刚烷胺 100 mg`（全部成分 + 各自含量） |
| 单方段污染 | — | 单方段 `.mkrow` 里 `tramacet/zaldiar/oxycodone/tramadol` 命中 **0** |
| 「不可互换」提示 | 有 | 有（`drug.notice` 原文未改，`不代表可以互换` 命中 true） |
| 四语段标题 | — | en `Only this ingredient / Combination products containing this ingredient`；es `Solo este principio activo / Asociaciones que contienen este principio activo`；zh-Hant `僅含此成分 / 含此成分的複方`；`matrix.multi_form` = `Multiple dosage forms / Varias formas farmacéuticas / 多剂型 / 多劑型` |

### 2.3 索引（`data/idx/core.json`）

```text
tylenol extra strength : f='multi'  fs=['tablet|500 mg','capsule|500 mg','liquid|960 mg/30 mL']  s=['500 mg','960 mg/30 mL','500 mg/950 mg']
panadol                : f='multi'  fs=['effervescent|1,000 mg','tablet|500 mg;325 mg','capsule|500 mg']
lipitor                : f='tablet' fs=None（单剂型不写，客户端用 s + f 回退）
```

| 指标 | v0.11.5 | v0.11.6 | Δ |
|---|---:|---:|---:|
| `core.json` raw | 45,243,092（43.15 MiB） | **46,295,974（44.15 MiB）** | +1,052,882 B（+1.00 MiB） |
| `core.json` gzip | 10,164,238 | **10,300,950** | +136,712 B |
| 48 MB 护栏 | — | **PASS** | — |

### 2.4 精度归整（plan §4）

- 规则落在 `_snap_strength()`：`v≥1 ∧ |v−round(v)|≤0.01 ∧ ≤2e-5×round(v)`。
- 命中：41 个 `500.x`（`499.9996×31`、`499.9995×2`、`500.0003`、`500.0053×3`、`500.0081×2`、`500.0082×2`）→ 显示 `500 mg`，与真实 `500 mg` **合并到同一行**（归整发生在分组键之前）。
- 反例保护（单测锁定）：`0.00025` / `0.0001` / `0.008` 不变（`v≥1` 门槛）；`469.01` / `100.008` / `790.02` / `666,666.666667` 不变（相对门槛）。
- **数据层零改动**：`product_component.strength_value` 与 `datapackage.json` 仍是 `499.9996`。
- 已知缺口：归整后这些值只在**折叠摘要**里出现（改前也是），折叠摘要不带「原记录」小字；可见行的「原记录」小字仍是 527 → 372 处（减少部分是行合并导致，且 42 个页面因此不再内嵌并排矩阵，见 §3）。

### 2.5 名称-规格冲突（机制，默认关闭）

- 开关：`SPEC_CONFLICT=1` + `data/sources/name_spec_conflict_20261114.csv` 在位才加载；默认构建日志 `spec conflict: off`，页面 0 条徽标（`data-spec-conflict` 计数 0）。
- 打开后：规格单元格追加 `<span class="tag warn" data-i18n="matrix.spec_conflict" data-spec-conflict="1000 MG" title="1000 MG">规格待核实</span>`；**不改数值、不改分组键、不改排序**（单测覆盖）。
- **为什么 v0.11.6 不开**（Lead 2026-11-14 定，T15 §6）：清单 614 行抽 40 条，约 37/40 是基准/口径差（盐型 `PRASUGREL 10↔12.17`、元素量 `CALCIUM SANDOZ 500↔2940`、提取物 vs 原料、净重 `24 G↔74.7 mg`），只有 3–4 条真冲突；全量打标会成片误报。
- **开之前缺什么**：`variant.base_fraction` 全是 1.0、`salt_code` 只有 15% 有值 → 名称里的量（元素/盐/提取物基准）与结构化含量无法放到同一基准上比较。

### 2.6 规模回归（对照 v0.11.5 `site/dist`）

| 指标 | v0.11.5 | v0.11.6 | Δ |
|---|---:|---:|---:|
| 文件数 | 125,510 | 125,515 | +5（索引变大后 shard 切片新增 5 个） |
| HTML | 125,290 | 125,290 | 0 |
| 成分页 / 名字页 | 12,438 / 80,885 | 12,438 / 80,885 | 0 / 0 |
| 总字节 | 974,169,676（929.0 MiB） | 992,410,495（946.4 MiB） | +18,240,819（+1.87%） |
| 成分页合计 / 平均 | 149.0 MiB / 12.3 KB | 155.3 MiB / **12.8 KB**（≤16 KB 目标） | +6.3 MiB |
| `sitemap.xml` URL | 66,300 | 66,300 | 0 |
| 0 字节文件 | 0 | 0 | 0 |
| acetaminophen 页 | 159,971 B | **238,208 B（1.489×，≤240 KiB）** | +78,237 B |

> 注：总字节里有 T12（品牌页/成分卡中文名 +6.5 MiB）与 T10（规格按剂型、复方段、`data-*` 属性）两部分；两次改动的产物都在同一个 `.tmp/dist-v0116` 里，数字是这个合并产物的。

## 3. 已知取舍 / 缺口（照实记）

1. **复方段每国只展开 5 行**（`COMBO_ROWS_PER_BLOCK=5`，plan 写的是 8）：12 行时 acetaminophen 页 299.6 KB，8 行 ~262 KB，5 行 **238,208 B（232.6 KiB）** 才压进 240 KiB。其余复方规格进折叠摘要（只列规格串，不列全部成分）——**完整成分清单在 `datapackage.json`**。
2. **内嵌并排矩阵的页面 922 → 812**：「≥2 国同规格行占比 ≥0.40」的分母现在包含新拆出来的复方行（复方通常单市场），110 个页面因此不再内嵌矩阵（列表视图完整、页面更小）。若要恢复，得给该判据加 mono/combo 权重，属新决策。
3. **`f='multi'` 的语义**：多剂型条目不再用「第一个剂型」代表整条记录；对 CSV 导出（`e.f` 列）现在会写 `multi`。
4. **明细桶（详情面板）仍是 `960 mg 30 mL` 空格写法**：`etl/build_detail_buckets.py` 不在本工位写权限 → 记 T10b，**没有**用正则去拆它的串。
5. **碱基/盐型**：`Atorvastatin` 与 `Atorvastatin Calcium` 是两个 `substance_id`，复方/单方与「部分相同」的判定沿用 `COUNT(DISTINCT substance_id)` 口径（与 `collision` 视图一致），不在此处做盐型折算。
6. **`fs` 组上限 3（不是 plan 的 4）**：4 组时 core 48.26 MB dec，超 Lead 的 48 MB 线；3 组 + 单剂型不写 + 紧凑串 = 46.30 MB dec（实测）。
7. **首屏守卫**：官方脚本本机仍跑不了（Chrome/Edge CDP 被沙箱挡，同 task-1）；成分页/结果页的替身度量与 atc4-ui 的对照由那边按 `reports/2026-11-14-after-compare.checklist.md` 跑。

## 4. 复跑命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'

& $py -m unittest tests.test_spec_grouping -v               # 16 项纯函数契约
$env:SITE_OUT='.tmp/dist-v0116'; & $py site/build.py        # == done ==
& $py deploy/ci_checks.py --fast --dist .tmp/dist-v0116      # PASS 8 / FAIL 0 / SKIP 4
& $py deploy/i18n_check.py                                   # FAIL 0 / WARN 2
& $py .tmp/t10_verify.py                                     # fs / 三案例 / 规模回归
$env:SPEC_CONFLICT='1'; & $py site/build.py                  # 只在验证冲突机制时开（默认关闭）
```
