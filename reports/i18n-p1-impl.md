# 三语 P1 实现报告（About / What's new / Confused / 404 + 许可 / ATC 双口径 / 内容更新）

> 任务：task-29。依据 `reports/i18n-audit-20261026.md` 的 P1 清单 + `reports/license-audit.md` §4。
> 改动文件：**仅 `site/build.py`**。未跑 git / 发布，未改 `site/dist`、`data/drugs.db` 或其他跟踪文件；
> **未改** `/* 搜索增强（task-28） */` begin/end 块与 `searchLayers*` 函数（搜索接入代码原样保留）。
> 构建：`SITE_OUT=.tmp/dist-i18n2`，产物 `.tmp/dist-i18n2/`；验收脚本 `.tmp/dist-i18n2/_verify/`。

---

## 0. 结论

| # | P1 项 | 状态 | 备注 |
|---|---|---|---|
| 1 | About 正文完整三语 | ✅ | 10 个正文块走 `data-i18n-html`（en/es/zh），EN fallback 直接写在 HTML 里；许可段三语并列（§4 原文） |
| 2 | What's new 正文三语 | ✅ | 标题/导语/「正文为中文」说明三语；release notes 正文保留中文（明确标注） |
| 3 | Confused 来源段三语 | ✅ | `conf.source_note` 三语（含 FDA 链接、可再发布对数动态、版权说明） |
| 4 | 404 页三语 | ✅ | 引入绝对路径 `i18n.js`，标题/说明/链接全部 data-i18n；`/es/**` 路径下 404 自动西语 |
| 5 | 移动端静态页收尾 | ✅ | 新增 `.tablewrap` 横向滚动（About 覆盖表）、release 表格可滚动、长词 `overflow-wrap`；UI P0 已做的 nav/页脚不重复 |
| 6 | 许可/署名（额外） | ✅ | WHO INN CC BY-NC-SA 3.0 IGO、ChEMBL CC BY-SA 4.0、datos.gob.mx CC BY 4.0、TGA © Commonwealth、CN 未找到再发布许可、AEMPS/COFEPRIS 待确认；链 `docs/许可清单.md` |
| 7 | ATC 双口径（额外） | ✅ | **动态计算**：全部 substance 47.5%（6,081/12,790）、药物实体 inn_drug 67.0%（5,757/8,592），不再是单一写死口径 |
| 8 | 合法药品示例（额外） | ✅ | About 示例改为 water pill / blood thinner / 睡前药 / the pill / statin；molly/lean/bars 仅作为「已排除」说明出现 |
| 9 | drug_term 计数 + 不含毒品说明（额外） | ✅ | `drug_term` 计数动态注入（当前 1,062 条）；明确「毒品与娱乐性用药黑话不在收录范围，已移除不再新增」 |

I18N：**137 → 160 keys × en/es/zh**（新增 23 键；0 缺失、0 空值、0 残留 `@@占位符@@`）。

## 1. 改动清单（`site/build.py` file:line）

| 内容 | 位置 |
|---|---|
| About 三语字典（10 块：title/lead/rules/nick/terms/sources/samename/gaps/analytics/stats） | `ABOUT_I18N` L482–784 |
| What's new / Confused / 404 三语字典（13 键） | `PAGE_I18N` L786–865 |
| ATC 双口径动态计算（DB + `data/entity_type.csv` 的 inn_drug） | `_atc_coverage()` L868–897 |
| 动态占位符（覆盖表/产品/成分/别名/昵称/drug_term/ATC 双口径） | `_i18n_placeholders()` L899–925 |
| 合并进 I18N + 占位符替换 | `_merge_static_i18n()` L927–937 |
| 许可/署名段（§4 三语并列 HTML，链 docs/许可清单.md percent-encoded） | `LICENCE_HTML` L939–1171 |
| About 页面重写（data-i18n-html 块 + 许可段 + 条件 analytics + stats） | `build_about()` L2969–2986 |
| What's new 三语头 + 语言说明 | `build_whats_new()` L2401–2410 |
| Confused 来源段走 `conf.source_note` | `build_confused()` L3023 |
| 404 三语 + 绝对 i18n.js | `build_404()` L3029–3061 |
| i18n.js 支持 `data-i18n-html`（innerHTML 替换） | i18n 生成段 L3276、apply() L3308–3309 |
| 静态页移动端收尾（`.tablewrap` / release 表格 / 长词换行） | CSS L1164–1170 |
| main()：算 ATC/drug_term → 合并三语字典 → **重写 i18n.js**（动态值必须在此之后） | main L3383–3387 |

## 2. 验收证据

```powershell
$py  = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$node= 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$env:SITE_OUT='D:\同种药物商品名剂量对应网站\.tmp\dist-i18n2'
& $py -X utf8 site/build.py        # == done ==, exit 0
& $node --check .tmp\dist-i18n2\assets\i18n.js   # exit 0
& $node --check .tmp\dist-i18n2\assets\app.js    # exit 0
& $node .tmp\dist-i18n2\_verify\i18n-p1.test.mjs # 6/6 PASS
& $py -X utf8 .tmp\dist-i18n2\_verify\static_check.py  # 59/59 PASS
# 临时 http.server 8794 抽查：i18n-p1-http.mjs → 23/23 PASS
```

- 构建：`drug pages 12377 / name pages 17861 / sitemap 30244 / total 160.5 MB`，30,259 个文件，exit 0；
  `site/dist` 未动（app.js mtime 仍 2026/10/26 20:46）。
- **行为测试 6/6**（Node vm 跑构建后的 `assets/i18n.js`）：
  ① es About 块 `data-i18n-html` 替换为西语 HTML；② About 五块 en/es/zh 各自为对应语言；
  ③ 许可段三语并列 + WHO INN / ChEMBL / datos.gob.mx / AEMPS / COFEPRIS / TGA / CN 齐全；
  ④ What's new / Confused / 404 三语替换正确，`/es/nope` → `Página no encontrada`；
  ⑤ ATC 双口径动态值（47.5% / 67.0%，含 6,081 / 5,757 / 8,592 分母）；⑥ `/es/` 直入写 localStorage。
- **静态验收 59/59**：I18N 160×3 一致；无 `@@` 残留；About 9 个 `data-i18n-html` 块 + 许可段
  （CC BY-NC-SA 3.0 IGO / ChEMBL / CC BY-SA 4.0 / datos.gob.mx / CC BY 4.0 / © Commonwealth of Australia /
  © His Majesty the King / 国家医保局 / 未找到开放的再发布许可 / AEMPS / COFEPRIS / ISMP/ECRI）；
  ATC 双口径数字与 inn_drug 分母说明；drug_term 计数；合法药品示例；排除毒品说明；
  What's new 旧中文标题已替换；Confused 来源段 + `.tablewrap`；404 绝对 i18n.js + 全 data-i18n；
  全站 `data-i18n`/`data-i18n-html` key 都在 en 字典里；三入口 hreflang/html lang 不回归。
- **HTTP 抽查 23/23**：`/`、`/es/`、`/zh/`、about/whats-new/confused/404 均 200 且无 `@@`；
  About 三语块 + 许可 + ATC 数字 + i18n.js 单次；404 绝对 i18n.js；`assets/i18n.js` 160 keys。
- 产物大小：`about.html 17,060 B`、`whats-new.html 21,689 B`、`404.html 1,739 B`、
  `assets/i18n.js 50,986 B`（含三语字典 + About 正文，gzip 后仍很小）、`style.css 8,075 B`。

## 3. 口径说明 / 已知风险

1. **ATC「药物实体 67.0% vs 任务文字里的 67.2%」**：现在是**构建期动态值**——`data/entity_type.csv`
   的 inn_drug 集合 ∩ 当前 `substance` 表：5,757 / 8,592 = 67.0%（全部 6,081 / 12,790 = 47.5%）。
   67.2% 是 `reports/atc-chembl.md` 里 ChEMBL 合并前的预估（5,777/8,595）；实际合并/后续数据任务后
   分子分母有微调。**代码不写死任何百分比**，下次数据变化会自动跟着变，建议对外引用以 About 现值为准。
2. **About 许可段为「三语并列」**：直接采用 `reports/license-audit.md` §4 的原文（EN/中文/ES 在同一段），
   这是许可原文的刻意并列，不是漏翻；如要严格按当前语言只显示一种，需拆成 3 个 key（P2 可做）。
3. **西语/英文正文为 AI 翻译**：术语（e.g. "market authorisation withdrawn"）建议后续由母语者抽检；
   页面无人工审核流程（项目约定纯 AI 验收）。
4. **未做**（按任务边界）：README/CHANGELOG 计数留给 Lead；`<title>`/meta description 本地化（P2）；
   About/What's new/Confused 的 `/es/`、`/zh/` 静态副本（P3）；数据层昵称西语解释（P2）。
5. **i18n.js 变大**：16 KB → 51 KB（未压缩，含 About 三语 HTML）。首屏仍只下 HTML/CSS/JS，
   无额外请求；gzip 后增量约几 KB，可接受。
6. **`data-i18n-html` 用 innerHTML**：内容全部来自构建期字典（非用户输入），无 XSS 面；
   但以后若把用户内容塞进这些 key 需改回转义。

## 4. 回滚方法

| 层次 | 操作 |
|---|---|
| 源码回滚 | `git checkout -- site/build.py` 后重新构建/发布（由 Lead 执行；本子智能体未跑 git） |
| 特性级回滚 | ① About 三语：删掉 `ABOUT_I18N` 合并（`_merge_static_i18n` 调用）并恢复旧 `build_about` 双语版；② What's new/Confused/404：各自删 data-i18n 属性即回到静态文案；③ ATC 双口径：删 `_atc_coverage` 调用、改回 `stats['atc_pct']` 单口径；④ i18n.js 的 `data-i18n-html` 循环可删（About 会显示 EN fallback） |
| 发布后回滚 | gh-pages revert 上一提交（改动集中在 `assets/i18n.js`、`assets/style.css`、about/whats-new/confused/404 四个页面；数据文件未变） |

## 5. 产物

- `site/build.py`：ABOUT_I18N / PAGE_I18N / _atc_coverage / _i18n_placeholders / _merge_static_i18n /
  LICENCE_HTML / build_about 重写 / build_whats_new / build_confused / build_404 / i18n.js apply / CSS。
- `.tmp/dist-i18n2/`：SITE_OUT 构建产物（30,259 文件）。
- `.tmp/dist-i18n2/_verify/{i18n-p1.test.mjs, static_check.py}`：可复跑验收脚本。
- `reports/i18n-p1-impl.md`：本报告。
