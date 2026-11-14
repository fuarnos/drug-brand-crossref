# 批次 C · 第 1 步：L7 次级页统一页头（施工图，未落盘）

> 工位：site-ui　｜　日期：2026-11-15　｜　状态：**计划稿（`site/build.py` 冻结中，等 Lead 说可以动手）**
> 规范来源：`reports/2026-11-15-ui-redesign-spec.md` §3-L7（验收 A12 / A13）、§1.1–1.3（token 与字号）、§4（串行顺序）。
> 本步只做 **L7**，一次构建可独立验收；L9/L10/L11… 在后续 7 步里各自独立。

## 0. 一句话方案

新增一个共用函数 `_page_head(...)`，输出固定的四件套
**返回路径 → h1 → 一句话摘要（≤1 行）→ 继续搜索入口**；
8 类次级页（drug / name / combo / maker / cat+atc / coverage / about / warn+confused）各自调用它；
**页头里的搜索框从现在的「页头 shell」搬进 `<main>`**（同一条 `_shell_search_html` 表单，只保留一份，避免两个输入框）。

```html
<nav class="crumbs" aria-label="Breadcrumb" data-i18n-aria="nav.crumbs">
  <a href="../index.html" data-i18n="nav.back_search">← Back to search</a><span> · </span>
  <a href="../atc.html" data-i18n="nav.categories">Categories</a>
</nav>
<h1>…</h1>
<p class="sub page-summary">…（一句话：这页是什么；不含结论）</p>
<form class="page-search" role="search" action="../index.html" method="get">
  <input id="hq" name="q" type="search" placeholder="…" data-ph="nav.search_compact" aria-label="…">
  <button type="submit" data-i18n="home.submit">Search</button>
</form>
```

## 1. 函数签名与位置

```python
def _page_head(prefix: str, title_html: str, summary_key: str | None = None,
               summary_html: str = "", crumb: str = "", search: bool = True) -> str:
    """统一页头四件套（L7）。title_html 已是 <h1>…</h1> 的完整 HTML（各页 h1 结构不同）；
    crumb 传 'atc' / 'coverage' 这类上级路径键；summary 走 i18n key（四语）。
    返回的 HTML 直接拼在 body 最前面。"""
```

- 放在 `_shell_search_html()`（≈8900）之后，`page()`（≈8931）之前；复用 `_shell_search_html()` 的 form 片段
  （把它抽成 `_search_form(prefix, compact=True)`，`page()` 里的 header 版本改为 `search=False` 时不再注入）。
- **`page()` 改动**：给 `page()` 加参数 `head_inside_main: bool = False`；为 True 时不再往 `<header>` 注入
  `.hsearch-row`（否则页面上会出现两个搜索框，且 `main` 里那个才是 L7 要的）。
- 调用点（按当前行号快照，按函数名搜）：
  | 页面 | 调用位置 | 参数 |
  |---|---|---|
  | 成分页 | `build_drug_pages()` body 首行 `<h1>{h1_inner}</h1>` | `crumb="atc"`；summary=`drug.summary`（新键） |
  | 商品名页 | `build_name_pages()` ≈11105 `body = f"""<h1>{esc(e['d'])}</h1>` | `crumb=""`（回搜索）；summary=`name.summary` |
  | 复方页 | `build_combo_pages()` ≈11775 | `crumb="atc"`；summary 复用现有 `combo.title`（「固定成分组合」） |
  | 厂商页 | `build_maker_pages()` ≈12317 | `crumb=""`；summary=`maker.summary` |
  | 分类页 / ATC | `build_category_pages()` ≈14257（已有 `cat.back` 链接）/ `build_atc_pages()` | 统一改用 `_page_head`（保留原 h1） |
  | 覆盖页 | `build_coverage_page()` ≈12823 | summary 复用 `coverage.sub`（若不存在则新键） |
  | 关于页 | `build_about()` ≈12721（`parts` 列表第一项） | 追加页内目录（L15 再做，本步只补四件套） |
  | 警示 / 易混淆 | `build_warn()` ≈3982 / `build_confused()` ≈12870 | 同上 |

## 2. CSS（复用现有 token，不发明新体系）

```css
.crumbs{font-size:13px;color:var(--muted);margin:0 0 6px}
.crumbs a{color:var(--accent);text-decoration:none}
.crumbs a:hover{text-decoration:underline}
.page-summary{font-size:14px;color:var(--muted);margin:0 0 10px;line-height:1.5}
.page-search{display:flex;gap:8px;align-items:center;margin:0 0 12px;max-width:600px}
.page-search input{flex:1;min-width:0;min-height:44px;padding:8px 12px;font-size:16px;
 border:1px solid var(--line);border-radius:10px}
.page-search button{flex:none;min-height:44px;padding:0 16px;border-radius:10px;
 border:1px solid var(--accent);background:var(--accent);color:#fff;font-size:15px;font-weight:600}
@media print{.crumbs,.page-search{display:none}}
```

## 3. 四语文案（新增 4 键，全部进 `UI_I18N` 四语 + `FR_I18N`）

| key | en | es | zh | zh-Hant | fr |
|---|---|---|---|---|---|
| `nav.back_search` | ← Back to search | ← Volver a la búsqueda | ← 返回搜索 | ← 返回搜尋 | ← Retour à la recherche |
| `nav.crumbs`（aria） | Breadcrumb | Ruta de navegación | 面包屑导航 | 麵包屑導覽 | Fil d’Ariane |
| `drug.summary` | Records for this ingredient, by country (identity only). | Registros de este principio, por país (solo identidad). | 这个成分在各国的登记记录（只做身份对应）。 | 這個成分在各國的登記記錄（只做身分對應）。 | Enregistrements de ce principe par pays (identité uniquement). |
| `name.summary` | Products recorded under this name, by market (identity only). | Productos registrados con este nombre, por mercado (solo identidad). | 这个名称下登记的各国产品（只做身份对应）。 | 這個名稱下登記的各國產品（只做身分對應）。 | Produits enregistrés sous ce nom, par marché (identité uniquement). |
| `maker.summary` | Products registered by this manufacturer, by market. | Productos registrados por este fabricante, por mercado. | 这个厂家登记的各国产品。 | 這個廠家登記的各國產品。 | Produits enregistrés par ce fabricant, par marché. |

（`nav.categories`、`home.submit`、`nav.search_compact` 复用现有键，不新增。）

## 4. 验收（照规范 A12/A13，全部可脚本复算）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# ① 四件套：main 内「h1 之上的返回链接 ≥1」「main 内搜索入口 true」「h1 恰 1 个」「h1~p.sub 可见行 ≤2」
& $py reports/2026-11-15-ui-baseline-probe.py --pages drug,name,combo,maker,cat,atc,coverage,about `
      --json .tmp/ui-baseline/l7-after.json
# ② 首屏守卫：页头变高 → 必须看 items / chrome 不退化
& $py deploy/first_screen_check.py --dist .tmp\v01111 --pages drug,name,coverage --viewports 390x844,1440x900
```

| 验收项 | 目标 | 检查方式 |
|---|---|---|
| A12 六类页头四件套 | **6/6 齐全**（drug/name/combo/maker/cat/coverage） | 探针 `head.back_link_count ≥1` 且 `head.search_in_main == true` |
| h1 唯一 | 每页 `main h1` 数量 == 1 | 探针 |
| 摘要行数 | `h1 ~ p.sub` 可见 ≤2（摘要 + 计数） | 探针 `head.sub_lines` 长度 |
| 页头高度 | 390 ≤295px（0.35×vh）、1440 ≤200px | 探针量 `.crumbs` 上缘到 `.page-search` 下缘 |
| 返回链接不 404 | 每个返回链接目标存在于产物里 | 脚本 `Path.exists()` |
| band/overflow | band 0.652–0.682、overflow 0 | `first_screen_check` 三档 |
| 正文/辅助字号 | 正文 ≥16、辅助 ≥13 | `first_screen_check` |

## 5. 体积预算（必须先跟 Lead 对齐）

名字页 **77,058** 个、成分页 **12,438** 个、复方页 **15,547** 个、厂商页 ~4.6k、分类/ATC ~500。
四件套每页静态度量（不含 i18n 字典）≈ **330–420 B**（crumb 90 + summary 60 + search form 230）。

| 方案 | 影响页数 | 估算增量 | 说明 |
|---|---:|---:|---|
| A：全部页都上完整四件套 | ~110k | **+36–46 MB** | 完全符合 A12；dist 从 1063 MB → ~1.10 GB（R2 免费额度 10 GiB 仍够） |
| B：名字页（77k）只给「返回链接 + 摘要」，搜索入口用纯链接 | ~77k | +12 MB | 探针 `search_in_main` 对 name 页会 false → **A12 不达标**，不推荐 |
| C：方案 A，但 search form 用极简写法（无 placeholder/aria 重复） | ~110k | +30 MB | 推荐 |

**建议 A/C**（规范明确 6/6，且 dist 仍在免费额度内）；请 Lead 在放行时确认体积口径。

## 6. 风险与回退

1. **`page()` 的 header 搜索框去重**：`hsearch-row` 现在在 8 类页面都存在，搬进 main 后要确认：
   ① 只留一份（`main` 里那份）；② `.has-q` 粘性搜索逻辑依赖 `.searchwrap`（首页），不受影响；
   ③ boot.js 注入的 `HS`（`_shell_search_html`）对长尾页仍会插 header 搜索栏 → 需要同步改 `boot_js_src`
   里「已有 `main .page-search` 就不再注入 header 搜索栏」的判断，否则长尾页会有两个。
2. **回退粒度**：`_page_head()` 与 8 个调用点各自独立；关掉只需让调用点不再拼接（`PAGE_HEAD=0` 开关可选）。
3. **首屏守卫的 `.mkblock h2` 选择器**：`_page_head` 不引入新的 h2，市场块 h2 不变，不受影响。
4. **77k 名字页是 slim 模板**：四件套必须走同一段 HTML（不做 per-page 特例），否则构建确定性/字节预算都不好核。

## 7. 下一步（本步完成后）

L9 成分页（中文名层级 / 筛选置顶 / 已选条件可取消）→ L10 名字页分段 → L11 复方页每成分一行 →
L12 厂商页搜索分页 → L13 分类页 → L14 覆盖页 → L15 关于/警示页；每步一次构建、一份报告、一次 `send_message`。
