# 批次 B 遗留回归：修复计划（并入 L7/L8 同批）

> 工位：site-ui　｜　日期：2026-11-15　｜　状态：**计划稿（`site/build.py` 冻结中，等 v0.12.0 发布后落盘）**
> 来源：Lead 2026-11-15 消息（`docs/img/v01110-mid-results-tylenol-390.png` 等）+ task-7 规范 §2（A1–A18）、§3-L2/L6/L8。

## 0.5 before 数字（v0.12.0 产物，只读探针现跑，供改后对账）

```powershell
& $py reports/2026-11-15-ui-baseline-probe.py --json .tmp/ui-baseline/v0120-before.json   # 18 组
```

| 页面 × 视口 | 边框 | 徽章（pill/box） | 最小字号 | 横向溢出 |
|---|---:|---|---:|---|
| results 390×844 | **118** | **39（pill 36）** | 13 | 否 |
| results 1440×900 | 249 | 85（pill 78） | 13 | 否 |
| drug 390×844 | 333 | 59（pill 59） | **12** | 否 |
| name 390×844 | 10 | 1 | 13 | 否 |
| combo 390×844 | 24 | 9 | 13 | 否 |
| maker 390×844 | 104 | 39 | 13 | 否 |
| cat 390×844 | 195 | **534（box 463）** | 12 | 否 |
| atc 390×844 | 50 | 145（box 124） | 13 | 否 |
| coverage 390×844 | 24 | 0 | 14 | 否 |
| home 390×844 | 33 | 9 | 13 | 否 |

L7 页头四件套 before（A12）：

| 页面 | h1 之上返回链接 | main 内搜索入口 | `h1 ~ p.sub` 行数 |
|---|---:|---|---:|
| home | 0 | 是 | 1 |
| results | 0 | 是 | 1 |
| drug | **0** | 是 | **6** |
| name | **0** | **否** | 3 |
| combo | **0** | **否** | 3 |
| maker | **0** | **否** | 2 |
| cat | 1 | 是 | 3 |
| atc | 2 | **否** | 5 |
| coverage | **0** | **否** | 2 |

→ 改后目标：drug/name/combo/maker/cat/coverage **6/6** 都有「返回 ≥1 + main 内搜索」，摘要行 ≤2；
（atc 与 cat 同属分类类，一并覆盖。）

**core.json 预期**：L7 + R1–R4 只改 HTML 模板与 CSS/文案，**不动索引字段**（`entries` / `core` 编码不变）
→ 改后 core.json raw/gzip **应零变化**；构建后我会贴 raw/gzip 实测值给 Lead 对账（上限 48 MB，现 45.67 MiB）。



| # | 现象（Lead 实测） | 根因 | 修法 | 归属 |
|---|---|---|---|---|
| R1 | 390 结果卡 **25/25 单元格截断**（药名只有 87px，内容要 380px） | 批次 B 把结果表改成 **5 列 + `table-layout:fixed`**，桌面正确；但手机上仍按 5 列排 → 每列 ~70px，全部省略 | **<768px 改卡片式**（每行 = 一张卡，字段竖排、`data-label` 作前缀），桌面保持 5 列表格 | L2 |
| R2 | 结果页每行 **8–10 处边框 + 24 个胶囊徽章** | 国家/剂型/状态仍是胶囊（`.tag` 带 1px 边框 + 底色），行内还有按钮边框 | 国家/剂型/状态 → **纯文字**（`--muted`，无边框无底色）；差异色只留 severe/warning/EU/picked/combo；行内按钮 → 无边框文字按钮 | L8 |
| R3 | 首页占位文字仍是旧长句 | `home.ph` 五语仍是「Brand name / generic name / nickname / a line from the pack」 | 改成规范 §3-L1 的一句式（zh「输入商品名、通用名或包装文字」/ en「Brand, generic or a line from the pack」/ es「Marca, genérico o una línea del envase」/ zh-Hant／fr 对应） | L1 |
| R4 | 「更新日志一句话」显示英文（界面语言非英文时） | 一句话是**服务端按路径语言**渲染的纯文本，没有 `data-i18n`；用户在根页用 `?lang=zh`/localStorage 切到中文时，其它文案被 i18n.js 替换，这一句不变 | 一句话改成 `data-i18n="rel.<version>"`；构建期把最近 3 版的一句话注入 5 语 `I18N`（动态键，不进静态字典）；服务端仍写英文兜底 | L6 |

## 1. R1：390 结果卡（最关键，改完要能量到）

```css
@media (max-width:767px){
  table.res.rows{display:block;border:0}
  table.res.rows thead{display:none}
  table.res.rows tbody,table.res.rows tr,table.res.rows td{display:block;width:auto}
  table.res.rows tr.br{margin:0 0 10px;padding:8px 0;border:0;border-bottom:1px solid var(--line-soft)}
  table.res.rows tr.br.picked{box-shadow:inset 4px 0 0 var(--accent)}
  table.res.rows td{padding:1px 0;white-space:normal;overflow:visible;text-overflow:clip}
  table.res.rows td::before{content:attr(data-label) " · ";color:var(--muted);font-size:13px}
  table.res.rows td.c-brand::before{content:""}
  table.res.rows td.c-brand{font-size:18px;font-weight:700;margin-bottom:2px}
  table.res.rows td.c-det{text-align:left;margin-top:6px}
  #reswrap{overflow-x:visible}
}
```

**验收（390×844）**：每格 `clientWidth ≥ 320px` 且 `scrollWidth ≤ clientWidth`（不再截断，25/25 → 0）；
单卡高 ~110–140px；首屏结果条目 **≥3**（规范 A5）；横向溢出 0（A8，`768` 档也要为 0）；
1440 仍是 5 列表格（A2 顺序不变）。

## 2. R2：边框 / 徽章收敛（L8 最小可验收集）

改 `marketTags()`（结果行）：去掉 `<span class="tag">`，改 `<span class="mktxt">US CA</span>`（`--muted` 13px、`tabular-nums`）。
改 `flatRowHTML()`：`form-tag` → 纯文字（剂型已并入「规格与剂型」列）；`badge`（severe/warning）保留；
`combo` / `picked` / `export` 保留差异色。CSS：`.tag` 默认去边框/底色；仅 `.tag.sev/.tag.warnwarn/.tag.eu/.tag.picked/.tag.combo`
保留；`.pickbtn/.detbtn` 移动端去边框（文字 + 下划线）。

**验收**：390 结果首屏胶囊 **64 → ≤24**（A4）；结果行国家胶囊 → **0**（A15 局部）；`tr.br` 边框 0（A3）；
390 结果页边框数 **131 → ≤72**（A17）；全站状态胶囊 150,651 → ≤16,512 与全站国家 48,315 → 0 用
`reports/2026-11-15-ui-badge-audit.py` 复算（该脚本是 phaseb-plan 的只读工具，可直接跑）。

## 3. R3：首页占位文字

`home.ph` 改为一句式（5 语，zh-Hant 值写进 `UI_I18N["zh-Hant"]`，避免 json 里旧值覆盖）；
同时把 `<input id="q" placeholder="…">` 的服务端兜底文本改成英文短句。

**验收**：390/1440 首页 `#q` 的 `placeholder` == 该语言 `home.ph`（4 个路径各 1 次），且长度 ≤ 该语言一句式；
`first_screen_check` home 的 A9（`#q` 上缘 ≤338px）不退化。

## 4. R4：更新日志一句话跟随界面语言

- 构建期：`_inject_release_liners()`——把 `load_releases()[:3]` 的每版一句话按 5 语写进
  `I18N[lang]["rel." + ver]`（动态键；`deploy/i18n_check.py` 只看静态字典，不会被这些键干扰）。
- 首页：`<span class="upd-liner" data-i18n="rel.v0.11.10">English fallback</span>`。
- `_optimize_home_html()` 的内联 i18n 字典会带上这几个键（每页 3 条 × ~60 字 ≈ 200 B）。

**验收**：根页 `?lang=zh` 时 `.upd-liner` 文本为中文（脚本断言含 CJK）；`/zh/index.html`、`/zh-hant/`、
`/es/index.html` 各自语言正确；切语言后 `apply()` 重跑仍正确。

## 5. 同批一起做（Lead 已定的 L7）

L7 四件套（`_page_head`）本轮一起落：返回路径 → h1 → 一句话摘要 → 继续搜索；8 类次级页调用；
体积 +36–46 MB（Lead 已批准）。

## 6. 落盘顺序与自验

1. R3/R4（首页两处，风险最低，先做）→ `build_index_page`/i18n 注入；
2. R1（移动卡片，CSS 为主）→ 390 结果卡验证；
3. R2（徽章/边框收敛）→ badge-audit 对账；
4. L7（页头四件套，8 类页面）→ A12 6/6；
5. 全量自验：`py_compile` / `i18n_check` FAIL 0 / `lib 61` / `etl 55` / `ci_checks --fast` PASS 8 /
   `first_screen_check` 三档（band 0.652–0.682、overflow 0、drug items ≥5、results 390 items ≥3）/
   `ui-baseline-probe`（A12/A17/A4）/ `ui-badge-audit`（A14/A15）。

每步一份 before/after 数字 + DOM 片段，落 `reports/2026-11-15-batchB-regressions.md`。
