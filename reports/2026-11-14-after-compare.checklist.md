# 改后核对清单（T10 + T12，v0.11.6） — 构建一落盘即可 5 分钟出结论

> 工位：atc4-ui ｜ 建立时间：2026-11-14 ｜ 配套：`reports/2026-11-14-before-baseline.md`（改前基线）、`reports/2026-11-14-before-baseline.measure.js`（度量脚本）、`reports/2026-11-14-after-compare.probe.js`（本清单的可执行版）
> 用法：**构建到 `== done ==` 之后**照 §5 的顺序跑；每条断言给「判定表达式 + 期望值 + 改前值」，红/绿一目了然。
> 红线：本清单只判定**身份对应与不可互换警示**是否达标，不判定疗效、不给剂量建议。

---

## 0. 开跑前的 4 个硬前置（任一不满足就停，别测）

| # | 判定表达式 | 期望 | 说明 |
|---|---|---|---|
| P1 | `(Get-Item site/dist).LastWriteTime` | 晚于 `2026-11-12 10:45:13` | 不改=构建没落盘 |
| P2 | `site/dist/index.html` sha256 | ≠ `d23cb742944d1049`（改前值） | 同上，抓「只改了源码没重建」 |
| P3 | 页脚版本串 | `v0.11.6` | 版本唯一来源是 CHANGELOG 第一节 |
| P4 | `Test-NetConnection 127.0.0.1 -Port 8000` | `True` 且 `& $py serve.py 8000` 是本轮新起的 | 旧进程会服务旧文件/占端口静默换 8001 |

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'
(Get-Item site/dist).LastWriteTime
& $py -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path('site/dist/index.html').read_bytes()).hexdigest()[:16])"
```

---

## 1. 断言 A：结果页 `/?q=Tylenol`（T10 主战场）

取证方式：**浏览器**（客户端渲染，静态 grep 抓不到）→ 内联跑 `reports/2026-11-14-after-compare.probe.js` 的 A 段。

| # | 判定表达式 | 期望 | 改前值 |
|---|---|---|---|
| A1 | `dose = tr(Tylenol Extra Strength).querySelector('.c-dose').innerText`；`!(/500\s*mg\s*\/\s*960\s*mg/.test(dose) && /片剂/.test(dose) && !/多剂型/.test(dose))` | **true**（不再「500/960 两个强度 + 单一剂型 片剂」并存） | **false**（`500 mg / 960 mg 片剂`） |
| A2 | `/960\s*mg\s*\/\s*30\s*mL/.test(document.body.innerText)` | **true**（`960 mg/30 mL` 出现） | **false**（只有 `960 mg`） |
| A3 | 该行剂型词计数：`/多剂型/.test(dose) \|\| (剂型词命中数 ≥ 2)` | **true** | false（仅 `片剂`） |
| A4 | i18n 键 `matrix.multi_form` 存在且 **zh / zh-Hant / en / es 四语齐全**（静态查 `site/build.py`） | **4/4** | 0/4（键不存在） |
| A5 | 该行 `tr.br` 仍只有 1 条（没把同一注册名拆成多行、也没把 CA/US 拆散到看不出对应关系）——若 T10 决定拆分，记录新行数并说明 | 人工确认 | 1 行 |
| A6 | 结果页仍是候选集语义：`共 N 条候选` + `结果永远是候选集，不是唯一答案` 仍在 | **true** | true |

> A3 的剂型词表：`片剂 / 胶囊 / 液体 / 粉末 / 颗粒 / 栓剂 / 泡腾剂 / 注射剂 / 外用 / 口服溶液`。

## 2. 断言 B：品牌页 `/name/tylenol-extra-strength.html`（T12）

取证方式：**浏览器**（客户端渲染）。

| # | 判定表达式 | 期望 | 改前值 |
|---|---|---|---|
| B1 | `main h2[1]` 附近（成分标题内/紧跟）的 `.nolang-badge` 数 | **0** | **1**（`Acetaminophen<span class="st-badge st-unknown nolang-badge">无中文名</span>`） |
| B2 | 页面 `无中文名` 徽标总数（`document.querySelectorAll('.nolang-badge').length`） | **0** | 1 |
| B3 | 存在 `h2` 文本含 `相关品牌名称与配方差异`（i18n 键 `fam.cmp_title`） | **true** | false（原 `同一品牌在其他市场的写法`） |
| B4 | `main.innerText` 中 `/碰撞/g` 计数 | **0** | **1**（`…属严重碰撞。`） |
| B5 | 连排重复：`/泰诺\s*泰诺(?!林)/g` + `/泰诺林\s*泰诺林/g` 计数，且 `main ul.sub li` 里「同一名字出现 ≥2 次」的条目数 | **0 且 0** | **2 且 2**（`泰诺 泰诺`、`泰诺林 泰诺林`） |
| B6 | `/泰诺(?!林)/g` 与 `/泰诺林/g` 各自总次数 | **各 ≤2**（名称列表 1 + 家族对比表 ≤1；警示句里合法提一次不算重复） | **3 / 3**（列表 2 + 警示句 1） |
| B7 | 家族对比区有可核对的表/卡：`fam.cmp_market / cmp_name / cmp_ing / cmp_rel` 四个表头或标签都在 | **4/4** | 0/4（无此结构） |
| B8 | 关系说明列只用「不可互换」类表述（`fam.rel.same / diff / partial / release / none`），不出现「等价 / 可替代 / 效果相同」 | **0 命中** | — |
| B9 | 摘要行仍给「写法 / 覆盖市场」，`覆盖: CA、US` 保留 | **true** | true |

## 3. 断言 C：成分页 `/drug/acetaminophen.html`（T10）

取证方式：**浏览器**（客户端渲染；`960 mg/30 mL`、499.9996 都要在渲染后的 DOM 里找）。

| # | 判定表达式 | 期望 | 改前值 |
|---|---|---|---|
| C1 | 段标题命中 `/仅含此成分/` 与 `/含此成分的复方/` 各 ≥1（`main h2, main h3` 文本） | **2/2** | 0/2（无分段） |
| C2 | 「仅含此成分」段 `innerText` 不含 `/tramacet\|zaldiar\|oxycodone\|tramadol/i`（**且必须真有该段**，没段就记 n/a，不许判绿） | **0 命中** | 无分段 → 记 n/a |
| C3 | 复方段首行文本包含 **≥2 个成分名** 且 **≥2 个含量数字**（如 `Tramadol 37.5 mg` + `Acetaminophen 325 mg`） | **true** | false（只靠长名里的 `37.5mg/325mg`） |
| C4 | `main.innerText` 中 `/960\s*mg\s*\/\s*30\s*mL/g` 计数 | **≥1** | **0** |
| C5 | 所有含 `499.9996` 的元素满足 `el.closest('small, .m-orig, .sub, .meta, [data-i18n="matrix.original"]') !== null` | **全部满足** | 该值当前不着色（`matrix.original`=「原记录」小字未包住它） |
| C6 | 归整显示：同组内出现 `500 mg`（写死的整数显示），而原始值仍可从 `.m-orig` / 「原记录」看到 | **true** | false |
| C7 | 结构没塌：`main h1` = `Acetaminophen`；`.mkblock` ≥ 11；`.mkrow` ≥ 100 | **true** | 11 块 / 110 行 |
| C8 | 「不可互换」类提示仍在（`/不可互换\|不代表可以互换/` 命中） | **≥1** | 1（`…不代表可以互换。`） |

> C1 的文案若 site-ui 落地成别的说法，**判定降级为人工**：把实际段标题抄进报告，并说明是否达到「先分单方/复方」的目的；不要把没有分段判成通过。
> C5 若页面根本没渲染出 `499.9996`（折叠在 +N 里），记 `n/a`，并改测「展开 AU 块后仍只在原记录小字里」或写「本项未覆盖」。

## 4. 断言 D：红线 grep（三页 + 静态）

取证方式：浏览器取 `main.innerText` 后跑正则；静态再扫一遍新增文案。

| # | 判定表达式 | 期望 | 备注 |
|---|---|---|---|
| D1 | 可见文本不含 `/(可以\|可)替代\|换药\|应服用\|recommended dose\|equivalent dose\|剂量换算\|equivalent to/i` | **0 命中** | **先剥合规句再测**：①`本站只做标识对应，不构成用药建议，不能替代医师或药师。` ②`不建议替换药品`（它含「换药」二字，实测是误报源）③`不做剂量换算` ④`不给用药建议` ⑤`这不是医疗建议。换药前请核对实际包装与成分，并咨询药师。` |
| D2 | 可见文本不含 `/collision/i`；DOM 无 `[class*="collision"]`、无 `data-collision` | **0** | `collision` 只在 `db/schema.sql` 视图里 |
| D3 | 新增文案不含 `/碰撞/`（品牌页/成分页/结果页） | **0** | `whats-new.html` 的历史 CHANGELOG 条目里有「碰撞」（8 行），**不计入**；about 页若保留「碰撞自动推导」需人工确认是否属公开口径允许 |
| D4 | 没有「剂量换算 / 等剂量 / 按体重给药」类句式：`/mg\/kg\|按体重\|等剂量\|换算成/` | **0** | 只做身份对应 |
| D5 | 每个结论性文案都带「候选集 / 不可互换 / 不代表可互换」之一 | **每页 ≥1** | 底线 1、3 |

## 5. 断言 E：规模与一屏护栏（改前基线对照）

取证方式：静态（python）+ 浏览器（复用 `reports/2026-11-14-before-baseline.measure.js`，12 组）。

| # | 判定表达式 | 期望 | 改前基线 |
|---|---|---|---|
| E1 | `data/idx/core.json` raw | **11–50 MB**，且本轮 **≤48 MB**（护栏顶 50 MB 下留 2 MB 余量） | 45,243,092 B（43.15 MiB） |
| E2 | `data/idx/core.json` gzip | **2.5–12 MB** | 10,164,238 B（9.69 MiB） |
| E3 | `site/dist` 0 字节文件数 | **0** | 0 |
| E4 | `site/dist` HTML 页数 | **≥ 119,026**（= 125,290 × 95%）；下跌 >5% 必须写原因 | 125,290 |
| E5 | `site/dist` 文件数 | ≥ 24,000（发布门槛） | 125,510 |
| E6 | 12 项测点横向溢出 | **0 / 12** | 0 / 12 |
| E7 | 首屏条目（1440：首页/结果/成分/品牌/覆盖/分类） | ≥ 改前 −5%，即 **11.4 / 4.275 / 8.55 / 2.85 / 6.175 / 9.975**；低于要写原因 | 12 / 4.5 / 9 / 3 / 6.5 / 10.5 |
| E8 | 首屏条目（390：同上顺序） | ≥ 改前 −5%，即 **8.075 / 0.95 / 5.225 / 2.85 / 1.425 / 1.425** | 8.5 / 1 / 5.5 / 3 / 1.5 / 1.5 |
| E9 | `sitemap.xml` URL 数 | ≥ 62,985（66,300 × 95%） | 66,300 |
| E10 | `<12px` 文字节点数（6 页 × 2 视口） | **0** | 0 |

> E7/E8 **不是越低越差**：T10 加了段标题/多一层结构，首屏条目天然会掉一点；掉 >5% 要写清「掉在哪一行」。品牌页 `.card` 从 1 变成「主卡 + 家族对比卡」，条目数会**上升**，属预期。

---

## 6. 选择器依赖清单（**交给 site-ui：请勿改名**）

改类名会让度量脚本与首屏守卫**静默失效**（选择器 0 命中 → 条目数 0 → 假绿/假红）。下面这些都已被 `deploy/first_screen_check.py` 或本轮脚本引用：

| 选择器 | 页面 | 依赖方 | 用途 | 能否改名 |
|---|---|---|---|---|
| `#reswrap`, `#reswrap table`, `#reswrap thead th` | 结果页 | 守卫 + 本轮脚本 | 结果表定位 / 表头断言 | 否 |
| `#reswrap tbody tr.br` / `tr.grp` / `.grp-tags` / `.grp-count` | 结果页 | 守卫 + 脚本 | 首屏条目数、分组表检测 | 否 |
| `.c-dose` | 结果页 | 脚本 | **T10 主战场**（剂量格） | 否 |
| `.form-tag` | 结果页 | 脚本 | 剂型标签（T10 会改语义，类名请留） | 否 |
| `.badge.combo` / `.tag.combo` / `.badge.sev` / `.badge.warn` / `.badge.export` | 结果页 | 脚本 | 复方/警示/出口徽标 | 尽量保留 |
| `main h1`, `main h2`, `main h3` | 全站 | 守卫 + 脚本 | 段标题、遮挡判定 | 否 |
| `main .card` | 品牌页 | 守卫 + 脚本 | 首屏条目 + 家族对比卡 | 否 |
| `main ul.sub li` | 品牌页 | 守卫 + 脚本 | 名称列表条目 | 否 |
| `.nolang-badge` / `.st-badge` / `.st-unknown` | 品牌页/成分页 | 脚本 | 「无中文名」徽标判定 | 否 |
| `.notice` / `.famnotice` / `.famnote` | 全站 | 守卫（chrome）+ 脚本 | 警示区 | `.notice` 否 |
| `.m-orig` | 成分页 | 脚本 | 「原记录」小字（499.9996 落点） | 否 |
| `.mkblock` / `.mkrow` / `[data-mk]` / `[data-spec]` / `[data-form]` | 成分页 | 守卫 + 脚本 | 国家块 / 规格行 / 过滤 | 否 |
| `.formchips` | 成分页 | 守卫（主操作） | 剂型 chips | 否 |
| `.matrix-filters` / `.mf-slot` / `details.mf-details` / `.mf-open` | 成分页 | 守卫（chrome） | 筛选面板 | 否 |
| `#covtable tbody tr`, `#covtable thead th` | 覆盖页 | 守卫 + 脚本 | 条目数 / 表头（「产品数→记录数」） | 否 |
| `ul.atcmembers li` / `ul.atclist li` | 分类页 / ATC 页 | 守卫 + 脚本 | 条目数 | 否 |
| `.catgrid a` / `.updlist li` | 首页 | 守卫 + 脚本 | 条目数 | 否 |
| `#q` | 首页/结果页 | 守卫（主操作） | 搜索框 | 否 |
| `header` / `footer` / `.tabbar` / `.restools` / `.covtools` / `.lang-menu` / `#ac` / `.sn-panel` | 全站 | 守卫（chrome 占比） | chrome 采样 | 否 |

**i18n 键依赖**（改文案可以，键名请留）：`matrix.multi_form`（新）、`matrix.original`、`matrix.spec`、`matrix.none`、`fam.cmp_title`、`fam.cmp_intro`、`fam.cmp_market/name/ing/rel/this`、`fam.rel.same/diff/partial/release/none`、`fam.warn`、`name.severe`、`name.no_zh`、`name.no_zh_hant`、`badge.combo`、`res.records_noun`。

---

## 7. 5 分钟执行顺序

```powershell
# ① 前置（30 秒）：dist 换没换、版本对不对
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'
(Get-Item site/dist).LastWriteTime
& $py -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path('site/dist/index.html').read_bytes()).hexdigest()[:16])"

# ② 静态断言（60 秒）：规模 / 0 字节 / 页数 / core.json / sitemap / i18n 四语 / 红线词
& $py - <<'EOF'   # 见 §8 静态脚本（复制进去直接跑）
EOF

# ③ 起预览（10 秒）
& $py serve.py 8000      # 另开窗口/后台，确认是 8000 不是 8001

# ④ 浏览器断言（90 秒）：把 reports/2026-11-14-after-compare.probe.js 全文粘进
#    mcp__browser__browser_run_code_unsafe 的 code 参数（该工具只允许读写
#    …\default-workspace\_tmp\browser-out\ 与 …\.dsh\profiles\desktop\，不能直接加载仓库文件）

# ⑤ 12 组度量（120 秒）：同上，粘 reports/2026-11-14-before-baseline.measure.js，截图落到
#    _tmp\browser-out\ 再 Copy-Item 进 docs/img/v0116-after-*.png
```

失败处理：**任一条红 → 写进报告并停**，不要用「整体看起来更好」盖过去；同一指标前后差 >5% 必须给原因（AGENTS §5）。

---

## 8. 静态断言脚本（可直接粘进 python）

```python
import gzip, re
from pathlib import Path

dist = Path("site/dist")
files = [p for p in dist.rglob("*") if p.is_file()]
html = [p for p in files if p.suffix == ".html"]
total = sum(p.stat().st_size for p in files)
core = (dist / "data/idx/core.json")
raw = core.stat().st_size
gz = len(gzip.compress(core.read_bytes(), 9))
locs = re.findall(r"<loc>(.*?)</loc>", (dist / "sitemap.xml").read_text(encoding="utf-8"))
build = Path("site/build.py").read_text(encoding="utf-8")

# 红线静态检查：先剥掉「合规的反向声明」，再匹配。否则「不建议替换药品」里的「换药」
# 会把合规句判成违规（2026-11-14 实测踩过）。
compliant = build
for s in ["不构成用药建议，不能替代医师或药师", "不建议替换药品", "不做剂量换算",
          "不给用药建议", "这不是医疗建议。换药前请核对实际包装与成分，并咨询药师。"]:
    compliant = compliant.replace(s, "")
redline = re.findall(r"(可以|可)替代|换药|应服用|recommended dose|equivalent dose|剂量换算", compliant)

checks = {
    "E1 core_raw<=48MB": raw <= 48 * 1024 * 1024,
    "E1b core_raw>=11MB": raw >= 11 * 1024 * 1024,
    "E2 core_gzip 2.5-12MB": 2.5e6 <= gz <= 12e6,
    "E3 zero_byte==0": sum(1 for p in files if p.stat().st_size == 0) == 0,
    "E4 html>=119026": len(html) >= 119026,
    "E5 files>=24000": len(files) >= 24000,
    "E9 sitemap>=62985": len(locs) >= 62985,
    "P3 footer v0.11.6": "v0.11.6" in (dist / "index.html").read_text(encoding="utf-8"),
    "A4 matrix.multi_form 键存在": "matrix.multi_form" in build,
}
for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k)
print("D1 静态红线候选（需人工看上下文，报告项不阻断）:", redline[:10])
print(f"core raw={raw} gzip={gz} files={len(files)} html={len(html)} sitemap={len(locs)} bytes={total}")
```

> **静态 D1 只作报告项**：源码里合规的反向声明和注释会误命中（实测「不建议替换药品」里的「换药」就命中过）。**阻断判定以渲染文本的 D1–D5 为准**；要看「新增文案」有没有引入违规，用 `& .\tools\git\cmd\git.exe diff -U0 -- site/build.py` 只看 `+` 行，且跳过 `#` / `//` / `*` 开头的注释行。

---

## 9. 本清单自己的限制

- A/B/C 全部依赖**客户端渲染后的 DOM**，静态 grep 抓不到；必须起预览 + 浏览器。
- 官方 `deploy/first_screen_check.py` 在本机起不来（`Chrome 未就绪（--remote-debugging-port 没起来）`，见改前基线 §1.1），所以 E6–E10 用替身脚本；**替身数字不能顶替官方门槛**，官方 7 项仍需在能开 CDP 的环境补跑，并在发布报告里写明谁补的。
- C1/C5 有「文案未定」与「值可能不渲染」两种降级路径，已在条目标注；降级不许判绿。
- 本清单不判定任何疗效/可替代性结论（红线）。

---

## 10. 自检记录：这套断言已经拿 v0.11.5 产物跑过（改前应当全红）

在写本清单时，已把 `reports/2026-11-14-after-compare.probe.js` 对**改前产物**（v0.11.5，dist mtime 2026-11-12 10:45:13）完整跑了两轮（第二轮用于验证断言修正），共 **37 条断言**：

| 结果 | 条数 | 分布 |
|---|---:|---|
| **红（fail）** | **19** | 正好是 T10/T12 要改的靶点 |
| 绿（pass） | 17 | 全是「必须保持不被改坏」的守卫项（候选集语义、结构没塌、不可互换提示、红线话术、规模护栏） |
| 灰（na，不许判绿） | 1 | C2：改前没有「仅含此成分」段 → 该断言无从成立 |

红项 → 靶点对照（改前实际值）：

| 断言 | 改前实测 | 归谁 |
|---|---|---|
| A1 / A3 | 剂量格 = `500 mg / 960 mg 片剂`（剂型词 1 个） | T10 |
| A2 | 全页无 `960 mg/30 mL` | T10 |
| A4 | `matrix.multi_form` 键不存在（0/4 语） | T10 |
| B1 / B2 | `Acetaminophen` 旁 1 个「无中文名」徽标（全页 1） | T12 |
| B3 | H2 = `["Acetaminophen无中文名","同一品牌在其他市场的写法"]` | T12 |
| B4 | 「碰撞」1 次（`…属严重碰撞。`） | T12 |
| B5 / B6 | 连排重复 2 处（`泰诺 泰诺`、`泰诺林 泰诺林`）；泰诺 3 次 / 泰诺林 3 次 | T12 |
| B7 | 家族对比 4 个标签只有 1 个命中（无对比表） | T12 |
| B9 | 品牌页无「不可互换」类提示 | T12 |
| C1 | 无单方/复方段标题（只有 11 个国别块） | T10 |
| C3 | 复方段不存在 → 成分/含量都取不到 | T10 |
| C4 | 全页 `960 mg/30 mL` 0 次 | T10 |
| C5 / C6 | `499.9996` 出现 1 次且**不在** `.m-orig`/「原记录」小字里 | T10 |
| D3[brand] | 仍出现「碰撞」 | T12 |
| D5[brand] | 品牌页无底线提示 | T12 |
| P3 | 页脚 `v0.11.5 · 2026-11-13` | 构建 |

两轮自检还修掉了 3 处**断言自身**的毛病，已写回脚本：

1. **C2 改前假绿**：没有单方段时「段内不含复方名」恒真 → 改成「必须真有该段，否则记 na」。
2. **B5/B6 口径太糙**：原来数「泰诺」总次数，会误伤警示句里合法提一次名字；改成判**连排重复** + 次数上限（列表 1 + 家族表 ≤1）。
3. **D1 静态误报**：「不建议替换药品」里就含「换药」二字，合规句会被判违规 → 先剥合规反向声明再测，且静态检查降级为报告项、以渲染文本为准。

跑法（复现）：

```text
① 起预览：& $py serve.py 8000
② 把 reports/2026-11-14-after-compare.probe.js 全文粘进 mcp__browser__browser_run_code_unsafe 的 code
③ 期望：改前 17 绿 / 19 红 / 1 灰；改后应变成「A/B/C/D3/D5/P3 全绿，红线项仍绿」
```

