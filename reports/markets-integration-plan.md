# 市场 / 语言注册表接入 `site/build.py` 改造方案（只读分析）

> 日期：2026-10-28 ｜ 状态：**只读分析，不改任何代码** ｜ 对应任务：task-55
> 前置交付（已存在）：`lib/markets.py`、`data/markets.json`（7 国 + TW 占位 + EU region）、
> `data/languages.json`（en/es/zh + zh-Hant 预留 + EU 语言占位）、`docs/市场扩展接口.md`、
> `tests/test_markets_registry.py`
> 目标：把 `site/build.py` 里「国家 / 语言」的硬编码迁到注册表，**分阶段、每阶段可独立验收与回滚**，
> 最终新增 TW / 繁中 / 未来 EU 只改 `data/*.json` + 文案，不改构建逻辑。

---

## 0. 结论（先看这里）

1. **硬编码点共 23 类结构点**（国家 13 类 / 语言 10 类），集中在 3 个位置：
   ① 顶部常量 + 6 个 i18n 字典；② 生成期页面模板（首页/成分页/覆盖表/About/warn/maker）；
   ③ 内联 JS（`APP_JS` 的国家视图 + `i18n.js` 的语言检测/切换）。
2. **名称迁移可以做到零字节差异**：注册表 7 国的 `name.en/es/zh` 与 build.py 现有
   `home.us…home.ca` 三语值**逐字一致**（`.tmp/markets-plan/name_parity.txt`），
   注入式迁移不会改页面文字；差异只可能来自**列表顺序**（选择器/成分页国家顺序）和
   `BUILD_V` 缓存戳——这两类已在 §5.4 的对拍里显式处理。
3. 推荐 **5 阶段**：
   - **Phase 0** 接线（挂 `lib.markets` + 只读守卫，输出零变化）；
   - **Phase 1** 语言接注册表（`LANGS`/hreflang/`i18n.js`/语言检测）；
   - **Phase 2** 国家接注册表（选择器/国家顺序/覆盖表/About/warn/maker/两个 JS 特例）；
   - **Phase 3** schema 耦合（`product.country` CHECK → `market` 表）+ TW / EU region 真正上线；
   - **Phase 4** 清理（删 legacy 顺序 shim 与重复 i18n key，补 build 级测试）。
4. **dummy 市场测试的硬阻塞**：现库 `product.country` 有 CHECK 枚举（`db/schema.sql`），
   **无法插入一个 dummy 国家的数据**。所以 dummy 测试分两层：
   - Phase 0–2：**注册表层 dummy**（dummy 语言生成 `/xx/` 落地页 + dummy 市场 enabled 但无数据 →
     build 成功、给出警告、不生成产品页/不进选择器）；**不需要写 DB**。
   - Phase 3 之后：DB 副本上完成 `market` 表迁移后，才能跑「dummy 市场带数据」的端到端 build。
5. **EU 不能直接当国家页**（会把多国产品混成一行，违反身份原则）：EU 只做 region 导航分组
   （`<optgroup>`/页头），不进国家选择器的 value、不进索引 `c` 字段、`?country=EU` 需被忽略。

---

## 1. 现状：硬编码点全量清单

> ⚠️ `site/build.py` 正被多个任务并行修改（当前 4,397 行 / 247 KB，2026-10-28 09:57 快照）。
> 下表的**行号只是快照**，patch 前用「锚点片段」重新定位（`grep -n` 即可）；行号漂移不影响方案。
> 覆盖产物基线：`site/dist` 50,864 个 HTML（`/es/`、`/zh/` 各 1 个落地页）、sitemap 50,863 个 URL、
> `data/index.json` 38.1 MB；首页 option 顺序 `US,GB,CN,ES,MX,AU,CA`、语言按钮 `en,es,zh`、
> hreflang `en,es,zh,x-default`（见 `.tmp/markets-plan/dist_baseline.txt`）。

### 1.1 国家相关（13 类）

| # | 位置（锚点） | 现状 | 迁移动作 | Phase |
|---|---|---|---|---|
| C1 | `I18N` 三语字典的 `home.us…home.ca`（约 L104-107 / L234-237 / L364-368，共 **21 个 key**） | 手写 7 国 × 3 语言 | 构建期从注册表注入同名 key（值逐字一致），静态 key 保留作 fallback | 1 |
| C2 | 首页国家选择器 7 个 `<option value="US"…>`（约 L3722-3729） | 手写 | 由 `reg.enabled_markets`（kind=country）生成；先走 legacy 顺序 shim | 2a |
| C3 | 成分页国家块顺序 `for country in ("US","GB","CA","CN","ES","MX","AU")`（约 L3280） | 手写元组 | 改为 `render_country_order()`；legacy 顺序先保持再切换 | 2a |
| C4 | 首页覆盖行 `covline = ", ".join(f"{r['country']} {n}")`（约 L3713、L3744） | 直接显示国家代码 | 用 `<span data-i18n="home.<cc>">CC</span>`，客户端本地化；或按语言分页面 | 2b |
| C5 | About 覆盖表 `COV`（`_i18n_placeholders` 约 L908-910） | `<td>{country}</td>` 原始代码 | 同 C4 的 `data-i18n` 方案（一张 About 页服务三语，避免按语言重建） | 2b |
| C6 | About 静态「Sources and coverage」段落（`about.sources`，约 L534-552；es/zh 同段） | 手写各国数据源说明 | TW/EU 上线前必须补三语文案；长期从注册表 `notes`/`docs/许可清单.md` 生成 | 2c |
| C7 | 索引 `c` 字段：`"c": sorted(a["c"])`（约 L3073）+ JS 国家标签渲染（约 L1750、L1864） | 数据驱动，代码本身通用 | 代码不改；加**构建期守卫**：`set(index c) ⊆ reg.enabled country codes`，否则告警/失败 | 0 |
| C8 | JS 澳洲 ARTG 兜底特例 `hasAU` / `c === 'AU'`（约 L2420-2421） | 硬编码 AU | 由 build 生成 `window.MARKET_CFG.artgFallback=['AU']`（值先不变），未来可选注册表 `ui` 字段 | 2a |
| C9 | 索引加拿大降权特例 `if "CA" in a["c"]`（约 L3098） | 硬编码 CA | 同 C8：`MARKET_CFG.namePenalty=['CA']` | 2a |
| C10 | `/warn` 国家标签（`_warn_meta_html` 约 L1238-1239） | 原始 `row["country"]` | 按语言把代码换成注册表名（该函数在 per-lang block 内，可直接传 `lang`） | 2b |
| C11 | 厂家页国家分组：`countries = sorted(...)`（约 L3631-3633）、标题 `esc(country)`（约 L3679） | 原始代码 + 字典序 | 顺序用 `render_country_order()` 过滤；标题用注册表名（per-lang block） | 2b |
| C12 | About 统计里的各国产品数表（`build_about` → `_i18n_placeholders`，约 L908） | 同 C5 | 同 C5 | 2b |
| C13 | 构建期查询 `coverage` / `source_cover ORDER BY country`（约 L4258-4265） | SQL 字典序 | 查询不改；**展示顺序**改由注册表 `order` 排（映射 `coverage` 行） | 2b |

### 1.2 语言相关（10 类）

| # | 位置（锚点） | 现状 | 迁移动作 | Phase |
|---|---|---|---|---|
| L1 | `LANGS = [("en","EN",""),("es","ES","es/"),("zh","中文","zh/")]`（约 L476） | 手写三元组 | `[(l.code, l.ui_label, l.path) for l in reg.enabled_languages]`；输出不变 | 1 |
| L2 | 语言切换 + hreflang（`page()` 约 L2772、L2779-2781） | 遍历 LANGS | 改读注册表（含 `hreflang` 字段），`x-default` 仍指英文根 | 1 |
| L3 | 三份落地页生成 `for code,_label,path in LANGS`（约 L3747-3753） | 三语言 | 同一循环改注册表 → 新语言自动生成 `/xx/index.html`、语言按钮、hreflang | 1 |
| L4 | `i18n.js` 内嵌字典 + 语言选择（`main()` 约 L4175-4247） | `window.I18N` 全量内嵌；`navigator.language.slice(0,2)`；默认 `'en'`；`langTarget()` 对 `en` 特判 | 新语言只影响 D 的 key 集合（自动）；检测改为「完整 BCP47 → 前缀匹配 → 默认语言（注册表 path=='' 的语言）」 | 1 |
| L5 | 6 个 i18n 字典常量：`I18N`(L96)、`ABOUT_I18N`(L486)、`PAGE_I18N`(L790)、`WARN_I18N`(L948)、`COMBO_I18N`(L1037)、`MAKER_I18N`(L1151)，各 3 语言段 | 每加一种语言要手写 6 段 | Phase 1 只接语言列表；**新增语言**需补 6 段（或未来抽 `data/i18n/<lang>.json`）。构建期断言：enabled 语言必须 6 段齐全，缺失则警告并回退 en | 1（新语言时） |
| L6 | `_merge_static_i18n` 的 `for lang in ("en","es","zh")`（约 L937） | 三语言硬循环 | 改为遍历注册表 enabled 语言；缺段回退 en | 1 |
| L7 | warn 数据行语言块 `for lang in ("en","zh","es")`（约 L1249、L1270） | 数据只有 zh/en/es 三列 | 新语言数据缺失时回退 en（该函数已注明「数据缺 es 时回退英文并标注」，扩为通用回退） | 1 |
| L8 | maker 语言块 `for lang in ("en","es","zh")`（约 L3641、L3687） | 同上 | 同 L7 | 1 |
| L9 | CSS `.lang-block[data-lang-block="en"]{display:block}`（约 L1555） | 无 JS 时只显示 en | 改为 `.lang-block{display:none}` + 默认语言规则；JS 已用 inline style 切换，不影响 | 1 |
| L10 | `404.html` `<html lang="en">`（约 L3872）、logo 中文副名（`page()` 内硬编码） | 固定 en | 404 保持 en（无语言路由）；logo 是品牌名，可保留 | 不改 |

### 1.3 相邻文件（不在本任务写范围，但迁移时要同步）

| 文件 | 现状 | 迁移时动作 |
|---|---|---|
| `site/build.py`（唯一生成器） | 本报告全部 patch 对象 | 分阶段改；**同一时间只允许一个会话改** |
| `db/schema.sql` `product.country CHECK (...)` | 7 国枚举 | Phase 3 才动（§4 / `docs/市场扩展接口.md` §5 迁移草案） |
| `tests/trilingual/run_tests.py` | 77 行含国家代码（用例数据，非注册表逻辑） | 新增市场/语言时补用例；docstring 的「主场国家」映射可从 `data/languages.json` 读取 |
| `db/check_data.py` | 美国术语样例（`WHERE p.country='US'`，2 行） | 可选：改成按 `reg.country_order` 抽样 |
| `README.md` / About / `CHANGELOG.md` | 覆盖数、国家数口径 | 每次新增市场/语言同步（同一组数字） |

---

## 2. 注册表 → build.py 的映射设计

### 2.1 构建期装载（Phase 0）

```python
# site/build.py 顶部（imports 之后）
from lib import markets as market_registry   # 纯读：data/*.json + 只读 DB source 表

# main() 开头（早于任何页面生成）
REG = market_registry.load()
_errors = REG.validate()
if _errors:                       # 默认只告警；SITE_STRICT_MARKETS=1 时失败
    print(f"!! markets registry: {len(_errors)} issue(s)")
    for e in _errors:
        print(f"   - {e}")
    if os.environ.get("SITE_STRICT_MARKETS") == "1":
        raise SystemExit(2)

MARKET_ORDER = REG.country_order                      # canonical: US,GB,CA,AU,ES,MX,CN
MARKET_BY_CODE = {m.code: m for m in REG.enabled_markets if m.is_country}
LANG_ORDER = [l.code for l in REG.enabled_languages]  # en,es,zh
```

构建期守卫（不改变输出，只防漂移）：

```python
def _assert_market_coverage(coverage_rows) -> None:
    db_codes = {r["country"] for r in coverage_rows}
    reg_codes = set(MARKET_ORDER)
    if db_codes - reg_codes:   # 库里有注册表未登记的国家 → 必须先改注册表
        print(f"!! DB countries not in registry: {sorted(db_codes - reg_codes)}")
    if reg_codes - db_codes:   # 注册表 enabled 但库里没数据 → 选择器/覆盖表策略见 §2.5
        print(f"!! enabled markets without data: {sorted(reg_codes - db_codes)}")
```

### 2.2 语言：把 `LANGS` 变派生值（Phase 1）

```python
# 替换 L476 的硬编码（保留旧常量一版，供回滚/对拍）
LEGACY_LANGS = [("en", "EN", ""), ("es", "ES", "es/"), ("zh", "中文", "zh/")]
LANGS = [(l.code, l.ui_label, l.path) for l in REG.enabled_languages]   # 值不变
```

- `page()` 的 hreflang 循环改用 `LANGS` 派生 + `REG.languages[code].hreflang`（zh-Hant 未来自动 `hreflang="zh-Hant"`），
  `x-default` 继续指根。
- 新语言落地页由 L3747 循环自动生成；sitemap 是 `rglob("*.html")`（L3910），**无需改**。
- `i18n.js` 检测建议：

```js
function pick(){
  var q = new URLSearchParams(location.search).get('lang');
  if(q && D[q]) return q;
  var seg = relPath().split('/').filter(Boolean)[0] || '';
  if(D[seg]) return seg;
  try{ var s = localStorage.getItem('lang'); if(s && D[s]) return s; }catch(e){}
  // 完整 BCP47 优先：zh-TW → zh-Hant（若启用），否则前缀；最后回退默认语言
  var tag = navigator.language || 'en';
  if(D[tag]) return tag;
  var base = tag.split('-')[0];
  if(D[base]) return base;
  return DEFAULT_LANG;   // 由构建期注入：注册表里 path=='' 的 enabled 语言（当前 'en'）
}
```

- **新语言（zh-Hant）最小改动**：`data/languages.json` enabled + 6 个 i18n 字典补 `zh-Hant` 段
  （或按 L5 的断言缺失回退 en）+ 数据行回退策略；构建逻辑不改。
- 数据层注意：`dose_warning` 的正文是 **zh/en/es 三列**；zh-Hant 页面按 L7 回退 en 并在页面标注
  （与现在「数据缺 es 时回退英文并标注」同一机制）。

### 2.3 国家名注入（零字节差异的关键）

```python
def _inject_market_names(reg) -> None:
    for lang, ldef in reg.languages.items():
        if not ldef.enabled or lang not in I18N:
            continue
        for m in reg.enabled_markets:
            if m.is_country:
                I18N[lang][f"home.{m.code.lower()}"] = m.display_name(lang)
```

- `data/markets.json` 的 7 国三语名与 build 现值逐字一致（`.tmp/markets-plan/name_parity.txt`），
  注入后 `i18n.js`（`window.I18N`）内容不变 → 页面字节不变。
- 静态 `home.us…` key 先保留（fallback），Phase 4 再删；不要反向手改 JSON 去迁就 build。

### 2.4 国家展示（Phase 2）

**选择器（C2）与首页**：

```python
def render_country_options() -> str:
    out = ['<option value="" data-i18n="home.all">All countries</option>']
    for code in RENDER_COUNTRY_ORDER:      # 见下方「顺序」决策
        m = MARKET_BY_CODE[code]
        out.append(f'<option value="{code}" data-i18n="{m.i18n_key}">{m.display_name("en")}</option>')
    return "".join(out)
```

**顺序决策（重要）**：现有两处顺序不同——
- 首页选择器：`US,GB,CN,ES,MX,AU,CA`
- 成分页国家块：`US,GB,CA,CN,ES,MX,AU`
- 注册表 canonical：`US,GB,CA,AU,ES,MX,CN`（`order` 10…70）

建议加**一版 legacy 顺序 shim** 保证 Phase 2 输出零差异：

```python
LEGACY_SELECTOR_ORDER = ["US","GB","CN","ES","MX","AU","CA"]
LEGACY_BLOCK_ORDER    = ["US","GB","CA","CN","ES","MX","AU"]
RENDER_COUNTRY_ORDER  = [c for c in LEGACY_SELECTOR_ORDER if c in MARKET_BY_CODE]
BLOCK_COUNTRY_ORDER   = [c for c in LEGACY_BLOCK_ORDER if c in MARKET_BY_CODE]
```

确认无回归后，Phase 2b 的独立版本切成 `MARKET_ORDER`（一次小版本，属用户可感知的排序变化，
写进 CHANGELOG），同时删 shim。**顺序变化不影响检索语义**（索引 `c` 是集合；前端只做 includes）。

**覆盖行 / About 表（C4/C5/C12）的本地化**：不要按语言重建 About 页，改用 `data-i18n`：

```python
# covline（首页）
covline = ", ".join(
    f'<span data-i18n="home.{r["country"].lower()}">{esc(r["country"])}</span> {r["n_products"]:,}'
    for r in coverage)
# About COV 表（_i18n_placeholders）
f'<td><span data-i18n="home.{r["country"].lower()}">{esc(r["country"])}</span></td>'
```

- `i18n.js` 的 `apply()` 会替换这些 `data-i18n` 文本 → 三语各自看到本国名，HTML 只生成一份。
- 只对「注册表 enabled 国家」生成 span；未知国家保留原始代码 + 告警（守卫 C7）。

**warn / maker 页（C10/C11）**：这两处在 per-lang block 内，直接传 `lang` 用
`MARKET_BY_CODE[code].display_name(lang)`；顺序用 `BLOCK_COUNTRY_ORDER` 过滤。

**两个 JS 特例（C8/C9）**：build 生成配置，值先不变：

```python
market_cfg = {"artgFallback": ["AU"], "namePenalty": ["CA"],
              "defaultLang": DEFAULT_LANG, "enabledCountries": list(MARKET_BY_CODE)}
# 插到 APP_JS 前：window.MARKET_CFG = {...};
```

JS 里 `'AU'`/`'CA'` 字面量改为 `MARKET_CFG.artgFallback.includes(c)` / `.namePenalty.includes(c)`。
未来若注册表加可选 `ui` 字段（如 `{"artgFallback": true}`），只改 JSON。

### 2.5 enabled 但无数据的市场策略（TW/EU 前必须定）

- **选择器**：只列 `enabled 且 coverage 有产品` 的市场（避免死选项）；enabled 无数据的市场 →
  构建日志警告（`enabled markets without data`），**不生成页面、不进选择器**。
- 覆盖行/About 表：只显示有数据的市场；EU region 不出现（region 无 coverage 行）。
- 新市场数据到位后自动出现在选择器/覆盖表——**无需再改 build.py**。

### 2.6 EU region 展示预留（Phase 3）

- `kind=region` 的市场 **永远不是** `<option value>`：不进选择器值、不进索引 `c`、`?country=EU` 被忽略
  （JS 里设置 `ctry.value` 后校验 `ctry.value === 'EU'` → 清空并提示）。
- 分组展示：`<optgroup label="Europe">` 来自注册表 `group` 或 `parent`：

```python
# 选择器分组草案：region（EU）→ 其子市场；无 parent 的按 group 分组
for grp in RENDER_GROUPS:            # "North America","Europe","Asia-Pacific","Latin America"
    out.append(f'<optgroup label="{esc(grp)}">')
    for code in RENDER_COUNTRY_ORDER:
        if market_group(code) == grp: out.append(option(code))
    out.append('</optgroup>')
```

- EU region 页面（可选、后续）：只做**导航/说明页**（列出成员国、EMA 集中审批标记、链到各国页），
  不含产品表、不混国家；`market.parent='EU'` 供未来成员国归类。
- 索引/搜索语义不变：`country` 过滤值仍是国家代码；region 只影响展示分组。

---

## 3. 分步 patch 清单

> 每个 Phase 独立提交/独立验收；改前先把 `site/build.py` 复制到 `.tmp/markets-plan/build-phaseN.py.bak`
> 作为对拍基线（build.py 正被其他任务并行改，提交前 rebase 到最新版本）。

### Phase 0 · 接线 + 只读守卫（0.5 天，输出零变化）

| 改动 | 锚点 | 逻辑 |
|---|---|---|
| 顶部 import + main 装载 | imports 区 / `main()` 开头（L4169 前） | `from lib import markets`；`REG = markets.load()`；打印 enabled 市场/语言摘要 |
| 注册表校验 | `main()` 开头 | `REG.validate()` 结果打印；`SITE_STRICT_MARKETS=1` 时 `SystemExit(2)` |
| 构建期守卫 | 读 `coverage` 后（L4258 附近） | `_assert_market_coverage(coverage)` 仅日志 |
| 对拍锚点 | — | 不改任何页面/JSON/JS 输出 |

**验收**：`python site/build.py`（`SITE_OUT=.tmp/markets-plan/dist-phase0`）成功；与 `site/dist`
逐文件对比仅 `BUILD_V`/版本戳不同；`python lib/markets.py --check` 通过。
**回滚**：纯新增，revert 该提交即可。

### Phase 1 · 语言接注册表（1 天，输出零变化）

| 改动 | 锚点 | 逻辑 |
|---|---|---|
| `LANGS` 派生 | L476 | 见 §2.2；保留 `LEGACY_LANGS` |
| `home.*` 名称注入 | `I18N` 定义之后（早于 `_merge_static_i18n`） | `_inject_market_names(REG)`；断言 21 个 key 全命中 |
| `page()` hreflang/切换 | L2772、L2779-2781 | 用 `LANGS` + `REG.languages[code].hreflang`；x-default 不变 |
| 落地页循环 | L3747-3753 | 已是 `LANGS` 派生，自动支持新语言 |
| `i18n.js` 检测/默认语言 | L4190-4239 | 完整 BCP47 → 前缀 → `DEFAULT_LANG`；`langTarget` 默认语言从注册表注入 |
| i18n 段完整性守卫 | `_merge_static_i18n`（L937） | 遍历 enabled 语言；缺段警告并回退 en |
| CSS lang-block | L1555 | 默认隐藏规则泛化 |

**验收**：同 Phase 0 对拍（应完全一致）；`zh-Hant` 仅注册表 enabled（I18N 段未补）时 build 不崩、
`/zh-Hant/` 落地页生成、语言按钮出现、缺 key 回退 en（dummy 测试 §5.3-T2）。
**回滚**：`LANGS = LEGACY_LANGS` 一行开关 + revert。

### Phase 2a · 国家顺序/选择器/JS 特例（0.5–1 天，输出零变化，legacy shim）

| 改动 | 锚点 | 逻辑 |
|---|---|---|
| 选择器生成 | L3722-3729 | `render_country_options()` + legacy 顺序 |
| 成分页国家顺序 | L3280 | `BLOCK_COUNTRY_ORDER`（legacy 元组） |
| 覆盖行 | L3713/L3744 | `data-i18n` span（三语客户端本地化） |
| About COV 表 | L908-910 | 同上 |
| JS 配置注入 | `APP_JS` 前（L1580 附近） | `window.MARKET_CFG`；AU/CA 字面量替换 |
| 守卫升级 | Phase 0 守卫 | 校验 index `c` 集合 ⊆ 注册表 |

**验收**：dist 对拍（顺序不变）；`?country=AU` 的 ARTG 兜底、CA 降权行为不变；三语检查覆盖行/About
显示本地化国家名（JS 生效后；静态 HTML 仍为代码 + `data-i18n`，属预期差异，写进对拍白名单）。
**回滚**：保留手写 option 字符串到 `.tmp` 对照；revert 提交。

### Phase 2b · 换成 canonical 顺序 + 本地化展示（0.5 天，用户可感知）

- `RENDER_COUNTRY_ORDER = list(MARKET_ORDER)`、`BLOCK_COUNTRY_ORDER = list(MARKET_ORDER)`；删 shim。
- warn/maker 页国家名/顺序改注册表（§2.4）。
- About `about.sources` 段落补 TW/EU 三语文案（C6）。
- CHANGELOG 写「国家列表按新顺序展示」这类小变化。
**验收**：新顺序与 `data/markets.json` 一致；sitemap/页面数不变；三语抽检。

### Phase 3 · schema + TW / EU 上线（1–2 天，依赖独立任务）

- 先做 `db/schema.sql`/`db/init_db.py` 的 `market` 表迁移（`docs/市场扩展接口.md` §5 草案，
  **需要备份 DB + 全量 rebuild 验证**，不与其它写库任务并行）。
- TW：`data/markets.json` TW `enabled:true` + `source_id`（ETL 先登记 source 行）+ `zh-Hant` enabled +
  i18n 段 + 验收查询（普拿疼/脈優/立普妥/威而鋼）。
- EU：region 保持 `enabled:false` 直到至少 1 个成员国 enabled；先 NL/IE/DE 试点，`parent="EU"`；
  选择器 `<optgroup>`（§2.6）；EU 不生成产品页。
**验收**：`db/check_data.py`、`tests/trilingual`、注册表测试、全量 build 到 `== done ==`、
sitemap/hreflang/语言切换抽检。

### Phase 4 · 清理（0.5 天）

- 删 `LEGACY_LANGS` / legacy 顺序 shim / 静态 `home.us…` 重复 key（改由注入生成 + 测试断言）。
- 抽纯函数到 `lib/markets_ui.py`（`render_country_options` / `market_label` / `js_market_config`），
  用 `tests/test_markets_registry.py` 或新增 `tests/test_markets_ui.py` 单测（不需要跑全量 build）。
- README/About/CHANGELOG 口径同步；`run_all.py` 在 build 前加 `lib/markets.py --check`（可选）。

---

## 4. 测试计划：dummy 市场 / 语言（重点）

### 4.1 需要的 build 环境开关（Phase 0 一起加，默认值保持现状）

| 环境变量 | 作用 | 默认 |
|---|---|---|
| `SITE_OUT` | 已有：输出目录（禁止直接写 `site/dist`） | `site/dist` |
| `SITE_MARKETS` | 覆盖 `data/markets.json` 路径（dummy 注册表） | 默认文件 |
| `SITE_LANGUAGES` | 覆盖 `data/languages.json` 路径 | 默认文件 |
| `SITE_STRICT_MARKETS` | 注册表/DB 不一致时让 build 失败（CI/发布护栏） | 不失败，只告警 |

> dummy 测试一律构建到 `.tmp/markets-plan/dist-*`，**不碰 `site/dist`、不发布**。

### 4.2 固定 fixtures（`.tmp/markets-plan/fixtures/`）

- `markets_dummy_market.json`：在现注册表追加 dummy 国家 `ZZ`（enabled，`source_id="manual_seed"`，
  `default_lang="en"`，`languages=["en"]`，order 95，无 DB 数据）。
- `markets_dummy_market_disabled.json`：同上但 `enabled:false`。
- `languages_dummy_lang.json`：追加 dummy 语言 `xx`（enabled，`path="xx/"`，`hreflang="xx"`,
  `default_country="ZZ"`；注意语言启用要求 ZZ enabled → 与上面的市场 fixture 配套）。
- `dist-baseline/`：Phase 0 前用当前 build.py 构建一次（`SITE_OUT`）作为字节对拍基线。

### 4.3 用例

| # | 用例 | 命令/断言 | 通过标准 |
|---|---|---|---|
| T1 | 注册表检查 | `python lib/markets.py --check` | exit 0 |
| T2 | **dummy 语言**（不发布数据） | `SITE_MARKETS=fixtures/markets_dummy_market.json SITE_LANGUAGES=fixtures/languages_dummy_lang.json SITE_OUT=.tmp/.../dist-dummy-lang python site/build.py` | build 成功；`dist-dummy-lang/xx/index.html` 存在；首页语言按钮含 `xx`；hreflang 含 `xx`；HTML `lang="xx"`；未翻译 key 回退 en（页面不空白）；**无 DB 数据写入** |
| T3 | **dummy 市场（enabled 无数据）** | `SITE_MARKETS=fixtures/markets_dummy_market.json SITE_OUT=... python site/build.py` | build 成功；日志告警 `enabled markets without data: ['ZZ']`；选择器**不含** ZZ（策略 §2.5）；不生成 ZZ 产品页；sitemap 不含 ZZ URL |
| T4 | dummy 市场 disabled | `SITE_MARKETS=fixtures/markets_dummy_market_disabled.json ...` | 与 T3 同（无 ZZ 任何痕迹），且无告警 |
| T5 | strict 守卫 | `SITE_STRICT_MARKETS=1` + 把测试库国家从注册表删掉（或注册表加未入库国家） | build 以非 0 退出，错误信息列出差异（发布护栏） |
| T6 | **等价性对拍（现网 3 语言）** | Phase 0–2 各阶段构建到 `dist-phaseN`，与 `dist-baseline` 逐文件比较 | 归一化 `BUILD_V`/`?v=\d+`/版本号后：HTML 文件数、sitemap URL 数、`data/index.json` sha、`assets/app.js` 与 `i18n.js` 语义一致；预期差异仅白名单（现代码里无；Phase 2b 顺序变化单列） |
| T7 | EU region 预留 | 注册表 EU 保持 disabled 构建 | EU 不出现在选择器/覆盖表/sitemap；若手工把 `?country=EU` 写进 URL，页面应清空选择器并正常显示（无报错） |
| T8 | dummy 市场带数据（**Phase 3 后**） | DB 副本 → 迁到 `market` 表 → 插入 `ZZ` 的 source+product+component → build | ZZ 出现在选择器/覆盖表；产品页可访问；country view 正常。**Phase 0–2 因 CHECK 枚举无法做**（见 §0-4） |
| T9 | 回归 | `python -m unittest tests.test_markets_registry -v`；`python tests/trilingual/run_tests.py`；`python db/check_data.py` | 全绿/无回归 |

### 4.4 对拍方法（避免「看起来一样」）

```powershell
# 1) 基线（当前 build.py）
$env:SITE_OUT=".tmp/markets-plan/dist-baseline"; python site/build.py
# 2) 候选（Phase N 改动后）
$env:SITE_OUT=".tmp/markets-plan/dist-phaseN"; python site/build.py
# 3) 归一化比较：去掉构建戳/版本戳后按文件 sha 比较；白名单写进脚本输出
```

比较脚本（放 `.tmp/markets-plan/compare_dist.py`，只读）：文件树/数量、每文件 sha256、
`sitemap.xml` URL 集合、`data/index.json` 的 JSON 结构 hash、首页 option/语言/hreflang 列表。
**白名单**只允许：`BUILD_V` 时间戳、版本号字符串、Phase 2b 的顺序变化、`data-i18n` 包裹导致的
HTML 文本化差异（Phase 2b 若采用 data-i18n 包裹国家代码，属预期，需在 Phase 2a 的对拍里预先说明；
如要求 Phase 2a 也零差异，可先保留原始文本、只加 `data-i18n` 属性而文本仍是代码，
`i18n.js` 运行时会替换）。

---

## 5. 风险与决策点

| # | 风险/决策 | 说明与建议 |
|---|---|---|
| R1 | **并行修改冲突（最高）** | `site/build.py` 正被其他任务改（索引 P1、UI P0 等）。迁移必须**串行**：先等 build.py 相关任务落地 → 重新对拍基线 → 再按 Phase 提交；本方案的 patch 锚点用片段搜索，不锁死行号 |
| R2 | 顺序变化 | 选择器/成分页国家顺序现有两套且与注册表 canonical 不同。建议 legacy shim（Phase 2a）保零差异，2b 再切 canonical 并写 CHANGELOG |
| R3 | 语言字典完整性 | 6 个 i18n 字典 + 数据行语言列（warn 只有 zh/en/es）是新增语言的最大工作量；建议 Phase 1 先做「缺段回退 en + 明确告警」，不许静默空白 |
| R4 | zh-Hant 数据语言缺口 | UI 可先上，但药品名/警示正文需数据侧支持；回退策略要写清（回退英文并在 UI 标注），不要让繁体用户看到空白 |
| R5 | schema CHECK 阻塞 dummy/新国家 | 新国家入库必须 Phase 3 迁移（`docs/市场扩展接口.md` §5）；Phase 0–2 的 dummy 测试不含数据路径 |
| R6 | About 静态文案 | `about.sources` 手写各国数据源；TW/EU 上线前必须补三语，且与 `docs/许可清单.md` 一致 |
| R7 | 覆盖统计口径 | 首页/About 的覆盖数来自 DB `coverage` 视图；注册表 enabled 但无数据的市场要显式告警，禁止显示 0 或空白 |
| R8 | AU 特例/CA 降权 | 先抽成 `window.MARKET_CFG` 值不变；若未来要按市场开关，注册表加可选 `ui` 字段（需同步 `lib/markets.py` 校验） |
| R9 | 旧 URL 兼容 | 现有 `?lang=en|es|zh`、`/es/`、`/zh/`、`?country=US` 全部保持；新语言只**新增** `/xx/` 落地页；region 不新增可分享的 `?country=EU` 语义 |
| R10 | 构建产物/SEO | hreflang 目前只在落地页输出（`alternates=True`），内容页靠 `?lang=`；新语言 SEO 建议后续评估是否给内容页加 hreflang（属独立改进，不在本次） |
| R11 | 性能/体积 | `i18n.js` 内嵌全量字典（当前 59 KB）；新增语言会线性增长，可接受；index/app.js 不变 |
| R12 | 发布纪律 | 只有 `deploy/publish.ps1` 一条发布路径；build 全量到 `== done ==` 才发布；同时间只允许一个会话 build |

---

## 6. 回滚方案

1. **代码级**：每个 Phase 一个提交；回滚 = revert 该提交 + 重新 build（旧 build.py 产物可直接重建）。
2. **Runtime 开关**：Phase 0–2 保留 `LEGACY_LANGS` / legacy 顺序 shim；紧急回滚只需把三个 shim
   常量改回硬编码（一处改动、无需回滚全部 Phase）。Phase 4 删 shim 前要确认已稳定 1–2 个版本。
3. **注册表级**：TW/新语言出问题 → `data/*.json` 里 `enabled:false` 即从构建中消失（无需改 build），
   再按需删除已生成目录（下次 build 会 `rmtree OUT` 重建）。
4. **DB/schema 级**：Phase 3 迁移失败 → 用 `data/backups/` 的 DB 备份整库替换；回滚流程与验收
   SQL 见 `docs/市场扩展接口.md` §5.3。
5. **发布回滚**：线上异常 → 发布上一个 tag 的构建产物（`DEPLOY.md`），不要手工推 `gh-pages`。

---

## 7. 依赖顺序与工作量

| 顺序 | 工作 | 前置 | 预估 |
|---|---|---|---|
| 0 | 等 build.py 相关并行任务落地、冻结基线 | 其他任务 | 0.5 天 |
| 1 | Phase 0 接线 + 守卫 + 对拍脚本 | — | 0.5 天 |
| 2 | Phase 1 语言接注册表（en/es/zh 零差异） | Phase 0 | 1 天 |
| 3 | Phase 2a 国家接注册表（legacy 顺序零差异） | Phase 1 | 0.5–1 天 |
| 4 | Phase 2b canonical 顺序 + 本地化展示 + About 文案 | Phase 2a | 0.5 天 |
| 5 | Phase 3 `market` 表迁移（独立任务/需备份 DB） | Phase 0 | 1–2 天 |
| 6 | TW 数据 + zh-Hant 文案（依赖 TW ETL） | Phase 1/3 | 1–2 天 |
| 7 | EU region 分组/试点（远景） | Phase 3 | 按成员国数据 |
| 8 | Phase 4 清理 + 测试固化 | 全部 | 0.5 天 |

**关键路径**：Phase 0 → 1 → 2a（可先发布一个小版本验证零回归）→ 2b；schema/TW 另起串行任务。
**不建议**一次大 PR 全改：对拍、回滚、并行冲突成本都会升高。

---

## 8. 验收 checklist（每个 Phase 复制使用）

- [ ] `python lib/markets.py --check` exit 0
- [ ] `python -m unittest tests.test_markets_registry -v` 全绿
- [ ] `SITE_OUT=.tmp/markets-plan/dist-phaseN` 构建到 `== done ==`
- [ ] 与 `dist-baseline` 对拍通过（或差异全在白名单内并解释）
- [ ] `python tests/trilingual/run_tests.py` 不回归
- [ ] `python db/check_data.py` 通过（Phase 3 后）
- [ ] 三语抽检（+ 新语言）各 3 条；hreflang/语言切换/0 结果提示
- [ ] 页面数、sitemap URL 数、`data/index.json` 大小无意外变化
- [ ] README/About/CHANGELOG 口径同步
- [ ] 由串行 owner 执行 build/publish（其他人不并发跑）

---

## 9. 证据文件（`.tmp/markets-plan/`，只读分析产物）

| 文件 | 内容 |
|---|---|
| `inventory.json` / `inventory.txt` | 首轮正则盘点（country/language/i18n 分组命中，含行号） |
| `domains.txt` | 按功能域抽取的全部国家/语言相关行（A–F 六组） |
| `sections1.txt` / `sections2.txt` | build.py 关键函数原文：LANGS/`_merge_static_i18n`/`_i18n_placeholders`/load_index/国家循环/build_index_page/seo/main/i18n.js 渲染 |
| `js_country.txt` | 内联 JS 的国家选择器/URL 状态/国家视图/AU 特例/初始状态（行号原文） |
| `stats.json` / `name_parity.txt` / `dist_baseline.txt` | 统计、注册表与 build 名称逐字一致性、dist 产物基线 |
| `*.py` | 上述内容的生成脚本（全部只读） |

---

## 10. 参考

- `docs/市场扩展接口.md` — 注册表字段、新增市场/语言 N 步、`market` 表迁移草案、TW/EU runbook
- `lib/markets.py` / `data/markets.json` / `data/languages.json` / `tests/test_markets_registry.py`
- `AGENTS.md` §4–§7 — 数据纪律、并行工位纪律、发布纪律
- `DEPLOY.md` — 发布/回滚唯一入口
