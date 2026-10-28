# v0.6.1 index.json 双写收尾实现报告（dist -54.9 MB）

> 任务：task-66（`site/build.py` + `deploy/publish.ps1` + `DEPLOY.md`/`README.md`，v0.6.0 之后）。
> 依据：`reports/index-legacy-removal.md`。
> 未跑 git/发布、未改 `site/dist`、`data/drugs.db` 或其他跟踪文件。构建：`SITE_OUT=.tmp/dist-legacy`。

---

## 0. 结果

| 指标 | v0.6.0 构建 | v0.6.1（本次） | 变化 |
|---|---:|---:|---|
| `site/dist` 体积（SITE_OUT 构建） | 450.4 MB | **395.5 MB** | **-54.9 MB** |
| 构建文件数（不含验收脚本） | 57,836 | **57,835** | **-1**（只少 `data/index.json`） |
| `data/index.json` | 55.1 MB | **不存在（默认停写）** | -55.1 MB |
| `data/idx/core.json` | 26.8 MB | **27.1 MB**（+`f` 字段） | +0.3 MB |
| core gzip | — | **6.4 MB**（`?legacy=1` 传输 9.29→6.4 MB，-31%） | — |
| `data/idx/legacy-mini.json` | — | 未生成（默认关） | — |
| 发布门禁 | 要求 `index.json ≥5 MB` | 改为 **`core.json` 存在且 ≥10 MB raw**（过渡期兼容旧 index.json ≥5 MB） | — |
| 核心条数 | 127,085 | 127,085 | 0 |

`?legacy=1` 现在与默认路径共用 **core.json + `decodeCore()`**；旧 index.json 仅在
`$env:WRITE_LEGACY_INDEX='1'` 过渡开关下继续生成。

## 1. 改动清单

### `site/build.py`
| 内容 | 位置 |
|---|---|
| 产物文档：index.json 标注「默认不再生成」、core 为唯一真相源、legacy-mini 可选项 | L13–15 |
| 默认停写 `data/index.json`（`WRITE_LEGACY_INDEX=1` 过渡写；构建日志标注 `legacy index.json: off/on`） | L5053–5075 |
| 可选二级兜底 `data/idx/legacy-mini.json`（`WRITE_LEGACY_MINI=1` 才写；core 子集列 k,d,dp,c,x,s,l,n,v,u） | L5065–5071 |
| `CORE_DICT_COLS` 与 `encode_core` 字段列表加入 `f`（B7 CSV 剂型列；字典列，实测 771 个唯一值） | L4690 / L4740 |
| done 摘要：`index.json` 行改为 `core.json`（含 legacy 开关状态） | L5169–5170 |
| 删除 app.js 版本替换链中已无引用的 `.replace("data/index.json", ...)` | `assets/app.js` 生成处 |
| `loadMainIndex()`：`?legacy=1` 与默认路径都走 `data/idx/core.json` + `decodeCore`；失败先尝试 `legacy-mini.json`，仍失败抛出 → 统一错误/重试 UI（不再请求 index.json） | L2841–2848 |

### `deploy/publish.ps1`
- 完整性检查（L110–126）：旧 `data/index.json ≥5 MB` 改为
  - 若存在旧 `data/index.json`（过渡期双写）→ 仍要求 ≥5 MB；
  - 否则要求 `data/idx/core.json` 存在且 ≥10 MB raw（当前 27.1 MB；gzip ~6.4 MB）。
- 头部说明同步（L10–12）。

### 文档
- `DEPLOY.md`（L31）：完整性检查改为 `data/idx/core.json`（≥10 MB raw；过渡期兼容旧 index.json）。
- `README.md`（L78–81）：说明默认只写 core、`?legacy=1` 共用 core 解码、`WRITE_LEGACY_INDEX=1` 过渡开关。

## 2. 验收证据

```powershell
$env:SITE_OUT='...\.tmp\dist-legacy'; & $py -X utf8 site/build.py   # == done ==, exit 0
& $node --check .tmp\dist-legacy\assets\app.js                      # 0
& $node --check .tmp\dist-legacy\assets\i18n.js                     # 0
& $node --max-old-space-size=6144 .tmp\dist-legacy\_verify\legacy_compare.mjs  # 对拍通过
& $node --max-old-space-size=4096 .tmp\dist-legacy\_verify\dom.test.mjs        # 4/4 PASS
& $py -X utf8 .tmp\dist-legacy\_verify\static_check.py                          # 26/26 PASS
# 临时 http.server 8802 + http_check.mjs → 12/12 PASS
# publish.ps1 语法解析（AST）0 错误 + 完整性门禁预演（core 分支/过渡分支）PASS
```

- **构建日志**：`core.json 27.1 MB (legacy index.json: off)`、`total size : 395.5 MB`、文件 57,835（不含 `_verify`）。
- **legacy 对拍**（真实 `app.js` 的 `decodeCore` 解码新 core，对照 v0.6.0 的旧 `data/index.json`）：
  **58 个 key × 24 个字段逐字段一致（0 mismatch，含新增 `f`）**；双方均 127,085 条；
  core `f` 列为字典列（`{d:[...], i:[每行下标]}`，`i` 长度 = 127,085）。
- **DOM 4/4**：① 默认路径 core+decodeCore 正常出结果（Lipitor）；② `?legacy=1` 同样走 core 解码正常；
  ③ core 404 → `legacy-mini.json` 兜底解码成功；④ core/mini 都失败 → 错误提示 + `data-retry` 重试按钮（不白屏、不再依赖 index.json）。
- **静态 26/26**：dist 无 `data/index.json`、无默认 legacy-mini；core ≥10 MB raw（27.1 MB）/ gzip 6.4 MB（<8 MB）；
  条数 127,085；core 含 `f` 字典列；app.js 不再有 index.json fetch 路径（注释可留）、含 legacy-mini 兜底与统一错误 UI；
  publish.ps1 有 core 检查且不再无条件要求 index.json；DEPLOY/README 已更新；体积 395.5 MB；sitemap 57,688；无 0 字节。
- **HTTP 12/12**：`data/idx/core.json` 200（≥10 MB raw，含 f 列，n=127,085）；`data/index.json` **404**；
  首页/assets/about/sitemap 正常；app.js 无 index.json fetch、含 legacy-mini 兜底。
- **发布门禁预演**（内联复刻 publish.ps1 逻辑，不做复制/提交/推送）：`publish.ps1` AST 语法 0 错误；
  `index.html` 存在；core 分支 25.9 MiB ≥10 MB；文件数 57,840（含验收脚本）≥24,000、无 0 字节；
  过渡分支：故意放入 <5 MB 的 index.json 会被门禁拒绝（防止半成品发布）。

## 3. 风险 / 注意

1. **旧缓存客户端**：≤v0.5.0 的 app.js 在刷新前仍会直接请求 `data/index.json` → 404；线上当前已是
   v0.5.5+（core+分片），影响仅限「浏览器缓存里仍是旧 app.js 的标签页/深链」，刷新后恢复。
   如线上观察到大面积 404，可临时 `$env:WRITE_LEGACY_INDEX='1'; & $py site/build.py` 恢复双写再发布。
2. **`?legacy=1` 语义变化**：从「旧 JSON 文件」变为「core 全量解码」（与默认路径同一份数据，行为一致；
   弱网传输 9.29→6.4 MB gzip，解析+解码 ~1.2 s）。旧文档/外部链接里的 `?legacy=1` 仍有效。
3. **legacy-mini 默认关**：只有构建时 `WRITE_LEGACY_MINI=1` 才生成；客户端会尝试它，但文件不存在时静默走错误 UI
   （多一次 404 请求，仅 core 损坏场景）。不建议默认开（+13 MB raw）。
4. **`f` 字段实测 771 个唯一值**（报告估计 ~9）：仍是小字典列，core +0.3 MB，无客户端引用（仅 B7 CSV 导出受益）。
5. **发布体积/时间**：dist -54.9 MB（-12%）、少 1 个 55 MB 文件，publish 拷贝/推送更快；GitHub 100 MB 单文件限制与
   50 MB 警告均不再触发（最大文件 core 27.1 MB）。
6. **收尾清理（v0.6.2 可选）**：删除 `WRITE_LEGACY_INDEX`/legacy-mini 过渡代码与 `?legacy=1`，按报告 Step 3。

## 4. 回滚

| 层次 | 操作 |
|---|---|
| 临时（不改代码） | `$env:WRITE_LEGACY_INDEX='1'; & $py site/build.py` → 恢复双写；publish.ps1 过渡分支接受旧 index.json |
| 源码 | `git checkout -- site/build.py deploy/publish.ps1 DEPLOY.md README.md` 后重建/发布（Lead 执行） |
| 发布后 | gh-pages revert 上一提交；数据/DB 未变，无数据风险 |

## 5. 产物

- `site/build.py`、`deploy/publish.ps1`、`DEPLOY.md`、`README.md`（见 §1）。
- `.tmp/dist-legacy/`：构建产物（57,835 文件 / 395.5 MB；无 `data/index.json`）。
- `.tmp/dist-legacy/_verify/{legacy_compare.mjs, dom.test.mjs, static_check.py, http_check.mjs, gate_sim.ps1}`。
- `reports/index-legacy-impl.md`：本报告。
