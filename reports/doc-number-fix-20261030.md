# 文档数字修正（2026-10-30）— 交接给发布经理统一提交

> 任务：Lead 2026-10-30 口头补充（流程文档收到后）｜性质：**只改文档数字与失效命令，不动规则**；未写代码、未构建、未发布、未提交。
> 数据来源：`site/dist` 与发布记录实测（2026-10-30，v0.9.0）。命令见 §3。

---

## 0. 改了什么

| 文件 | 改动（before → after） |
|---|---|
| `docs/网站优化流程.md` | §6.2-1：页面文案「首搜 ~0.2 MB 分片」改为「**该数字待 v0.9.1 实测更新**（文案修正由建站岗在 v0.9.1 处理）」，并保留 v0.9.0 实测（前缀分片中位 1.04 MB raw / 最大 1.10 MB；core 8.68 MB gz 后台加载） |
| `.dsh/skills/site-build/SKILL.md` | 旧数字/失效命令更正：dist「约 3 万文件 / 130+ MB」→ **116,883 文件 / 770.8 MB**；完整性检查 `data/index.json` → **`data/idx/core.json`**（≥10 MB raw；v0.9.0 实测 35.8 MB raw / 8.68 MB gzip）；文件数注释补实测 116,883；目录结构「drug ≈1.2 万 / name ≈1.8 万」→ **drug 1.24 万 / name 7.7 万（单包装轻量页 4.4 万，noindex）**；首屏/索引回归行改为实测（首屏 311 KB raw / 104 KB gz；索引 = core.json + 前缀分片，中位 1.04 MB raw） |
| `DEPLOY.md` | Netlify 段「`site/dist` 约 30,750 个文件 / 124 MB」→ **116,883 个文件 / 770.8 MB（v0.9.0 实测）**；其余发布规则/阈值不动 |
| `AGENTS.md` §6 | 「`data/index.json` ≥ 5 MB」→ **`data/idx/core.json` ≥ 10 MB raw**（v0.9.0 实测 35.8 MB raw / 8.68 MB gzip；`data/index.json` 自 v0.6.1 起不再生成）；只改这一处数字/文件名，不动规则 |

> 未改：`publish.ps1` 的实际门槛（文件数 ≥24,000、core ≥10 MB raw、0 字节=0、构建未在跑）；`AGENTS.md` §5 的流程链接（前一任务已加）。

## 1. 为什么改

- v0.9.0 后 `site/dist` 已是 **116,883 文件 / 770.8 MB**（单包装名字页 + 全量厂家页 + HK），旧文档的「3 万文件 / 130 MB」会误导体积回归判断；
- `data/index.json` 自 **v0.6.1** 起已从构建产物移除，唯一搜索索引是 `data/idx/core.json`（旧检查命令/清单会让新会话误判「构建不完整」）；
- 「首搜 ~0.2 MB」是页面文案旧值：实测前缀分片中位 1.04 MB raw、core 8.68 MB gzip 后台加载——**文案修正归建站岗 v0.9.1**，本文档只标注「待更新」，不替建站岗改页面文案。

## 2. 范围与纪律

- 只改数字与失效命令**，不动任何规则/流程/阈值**（publish 门槛、红线、发布顺序保持原样）；
- 文件：`docs/网站优化流程.md`、`.dsh/skills/site-build/SKILL.md`、`DEPLOY.md`、`AGENTS.md` §6；
- **不提交**：等发布经理（index-p1）统一提交；未改 `site/build.py`、DB、`site/dist`。

## 3. 复核命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

# dist 实测（文件数 / 体积 / 0 字节 / core raw+gz / sitemap）
(Get-ChildItem site/dist -Recurse -File).Count
[math]::Round((Get-ChildItem site/dist -Recurse -File | Measure-Object Length -Sum).Sum/1MB, 1)
(Get-ChildItem site/dist -Recurse -File | Where-Object Length -eq 0).Count
(Get-Item site/dist/data/idx/core.json).Length
(Select-String -Path site/dist/sitemap.xml -Pattern '<loc>' -Encoding UTF8).Count
& $py -c "import gzip,pathlib; p=pathlib.Path('site/dist/data/idx/core.json'); print(len(p.read_bytes()), len(gzip.compress(p.read_bytes(),6)))"

# 确认 index.json 已不存在（v0.6.1 起）
Test-Path site/dist/data/index.json    # 期望 False

# 文档里的旧数字应已清除（期望无输出/仅历史说明）
Select-String -Path .dsh/skills/site-build/SKILL.md,DEPLOY.md -Pattern '30,750|约 3 万|130\+ MB|data/index\.json' -Encoding UTF8
```

实测值（2026-10-30）：**116,883 文件 / 770.8 MB / 0 字节 0 / core 35,790,720 B raw（8,676,313 B gz）/ sitemap 68,430 / `data/index.json` 不存在**。

## 4. 遗留提示

- ~~`AGENTS.md` §6 的 `data/index.json` 旧门槛~~ → **已按 Lead 2026-10-30 指示一并更正**（core.json ≥10 MB raw；实测 35.8 MB raw / 8.68 MB gzip）。
- 页面 HTML 内「~0.2 MB」文案仍在线（v0.9.0 构建产物），v0.9.1 由建站岗修正后本文档 §6.2-1 可改为「已更新（实测值）」。
- 其余文档未逐份排查旧数字：引用站点体积/文件数时以 `docs/网站优化流程.md` §6.1 实测为唯一口径。
