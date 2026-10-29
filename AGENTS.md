# AGENTS.md

本仓库是「药品商品名跨国定位站」：给一个名字（商品名 / 通用名 / 俗称 / 包装上一行字），定位它是哪个药、什么规格，再给出其他国家的对应产品。

这个文件是给所有在本仓库工作的 agent（主会话、子会话、teammate）的常驻规则。**动手前先读完这一页。**

更长的背景：[README.md](README.md)、[docs/方案与数据模型.md](docs/方案与数据模型.md)、[DEPLOY.md](DEPLOY.md)。

## 1. 三条底线（不可违背）

1. **商品名不是主键**：查询永远返回候选集，唯一性由「国家 × 剂型 × 规格 × 活性成分」锁定。
2. **碰撞自动推导**：`collision` 视图按「不同成分数」「释放机制」分级，不手工标注；只有「品牌家族」是人工表。
3. **不给用药建议**：只做身份对应和「不可互换」警示，不输出剂量换算后的服药方案。

## 2. 环境

- Windows + PowerShell，仓库根就是工作目录，命令都在根目录跑。
- Python：`C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`（3.12）。下文统一写成 `$py`：

  ```powershell
  $py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
  ```

- Git 在本机不在 PATH，用仓库自带的便携版：`& .\tools\git\cmd\git.exe status`（`tools/` 被 gitignore，换机器要自备 git）。
- **没有 CI**：本地跑测试就是唯一门槛。仓库在 `main`，远端 `origin` = `github.com/fuarnos/drug-brand-crossref`。

## 3. 常用命令

| 目的 | 命令 |
|---|---|
| 建 / 升级库 | `& $py db/init_db.py` |
| 全量重建（备份库 → 入库 → 种子 → 建站） | `& $py run_all.py` |
| 只重建站（跳过入库） | `& $py run_all.py --no-ingest` |
| 建站 | `& $py site/build.py`（等终端出现 `== done ==`） |
| 本地预览 | `& $py serve.py 8000` → http://127.0.0.1:8000/ |
| 数据体检 | `& $py db/check_data.py` |
| 临时 SQL | `& $py db/q.py "SELECT ..."` |
| 单条查询 | `& $py cli.py "泰诺"` |
| 进度快照页 | `& $py render_dashboard.py` |
| 手机看板（进度 + 指令队列） | `& $py mobile/server.py`（或双击 `手机看板.cmd`）→ http://127.0.0.1:8787/ |
| 手机看板 · 外网 / 4G | `& $py mobile/server.py --tunnel`（cloudflared 快速隧道，见 `docs/手机通道.md`） |
| 手机指令：看有没有待办 | `& $py mobile/inbox.py pending` |

测试四套，改到哪层跑哪套，发布前全跑：

```powershell
& $py -m unittest discover -s etl -t etl      # 归一化 + 各入库
& $py -m unittest discover -s lib -t lib      # 检索 / 碰撞
& $py -m unittest tests.test_mobile_inbox -v  # 手机通道：队列 / CLI / 端点
& $py tests/trilingual/run_tests.py           # 三语检索一致性（只读开库）
```

## 4. 数据纪律

- `db/schema.sql` 是**单一真相源**；改表必须同时改 `db/init_db.py` 的幂等迁移（加列用 `ALTER TABLE ADD COLUMN`；`country` 的 CHECK 枚举只能重建表，init_db 已实现迁移路径，不要绕过）。
- `data/drugs.db` 可重建、不入库；`data/raw/` 是抓取缓存、不入库；`data/sources/` 是进仓库的小快照。`run_all.py` 会自动备份库到 `data/backups/` 并只留最近 5 份；**单独跑 ingest 不备份**，重要改动前先手动复制一份。
- 许可先行：新数据源先查清再落 `docs/` 结论；页面必须署名并链回原文；不确定就标「待确认」（当前西班牙、墨西哥待确认，中国没找到明确再发布许可）。
- 计数口径统一：README / About 页 / CHANGELOG / `coverage` 表用同一组数字；入库后条数变了要一起改。**不要照抄旧数字，以 `data/drugs.db` 现查为准。**
- 俗称 / 旧名 / 网络叫法进 `nickname` 表（指向活性成分），**不进 `product_name`**；只做精确匹配，逐条写出处。
- 新增人工数据前先看 `data/sources/` 是否已有官方快照可复用。

## 5. 验收门槛

| 改动 | 必须做 |
|---|---|
| `etl/**` | 重跑对应 ingest → `db/check_data.py` → 条数变化写进 CHANGELOG / README |
| `lib/search.py`、归一化 | 对应 unittest + `tests/trilingual/run_tests.py` |
| `site/build.py`、页面 / 前端 | 全量建站到 `== done ==`；三语各抽 3 条检索；页数 / 索引大小 / 首屏体积回归；链接、404、sitemap 抽检 |
| 页面文案 | zh / en / es 三语同步，别只改一种 |
| `db/schema.sql`、`db/init_db.py` | 老库能直接升级（幂等）；重跑 init_db 验证 |

> 站点 / 前端 / 文案改动的**完整优化流程与发布前 12 项 / 发布后 6 项清单**见 [docs/网站优化流程.md](docs/网站优化流程.md)（外部标准映射 + 命令 / 判定值）。

## 6. 发布纪律

- 唯一入口是 `deploy/publish.ps1`（或双击 `发布网站.cmd`），**绝不手工往 `gh-pages` 推**。曾发生过 `site/build.py` 还在写页面就推送、整站 404 的事故，见 [DEPLOY.md](DEPLOY.md)。
- 顺序：① `CHANGELOG.md` 最上面加一节 `## vX.Y.Z — YYYY-MM-DD`（2–5 条用户能感知的变化）→ ② `& $py site/build.py` 等 `== done ==` → ③ `& .\deploy\publish.ps1` → ④ `git tag -a vX.Y.Z` + GitHub Release（正文用 CHANGELOG 那一节）。
- 版本号唯一来源是 CHANGELOG 第一节；站点页脚、`whats-new.html`、GitHub Release 都从它生成。
- `publish.ps1` 自带完整性检查（`index.html`、`data/idx/core.json` ≥ 10 MB raw（v0.9.0 实测 35.8 MB raw / 8.68 MB gzip；v0.9.1 AU 全量后 41.3 MB raw / 9.67 MB gzip，**2026-10-30 起 `verify_live.py` 护栏为 gzip 2.5–12 MB / raw 11–50 MB**；`data/index.json` 自 v0.6.1 起不再生成）、文件数 ≥ 24,000、无 0 字节文件、构建未在跑）；失败会保留临时目录，别手动清理。
- 回滚要人来拍板：先 `-DryRun` 检查，再考虑重新发布上一个 tag 的构建产物。

## 7. 并行工位纪律（多个会话 / 队友共享同一工作区）

- 同一时间只允许一个会话跑 `site/build.py` 或 `publish.ps1`，否则会互相踩 `site/dist` 或抢发布。
- 动 `data/drugs.db`（重建、迁移、入库）之前，先在任务或消息里写明；不要和其他入库任务并行。
- 结论落到 `reports/` 或 `docs/`，不要只留在对话里——跨会话交接靠工作区文件，不靠上下文。
- 一次提交一个主题；不顺手格式化无关文件；提交信息沿用现有风格（`v0.3.4: ...`、`MX strength: ...`、中文描述）。
- 不碰别的会话正在改的文件；需要共享文件时先发消息协调。

### 手机指令队列（每次开工先看）

人不在电脑前时用手机看板留言，指令落在 `inbox/commands.jsonl`（append-only），agent 的回帖落在
`inbox/replies.jsonl`；**状态由最后一条回帖推导，不手工改历史行**。开工第一件事：

```powershell
& $py mobile/inbox.py pending                                        # 有就照着做
& $py mobile/inbox.py done <cmd_id> "做完的说明（带 reports/ 路径）"   # 做完回帖
& $py mobile/inbox.py blocked <cmd_id> "卡在哪、需要人定什么"
```

- 手机指令是**人的原话**，不是已完成的任务；涉及删数据、发布、花钱、改公开口径，仍按 §6 / §11 先问人，不要照着队列直接执行。
- `inbox/*.jsonl` 只通过 `mobile/inbox.py` 或手机页面追加；不手工编辑、不删历史行。
- 手机看板对 `data/drugs.db` 只读，不建入库/写库路径。

## 8. 报告与截图

- 报告放 `reports/`，命名跟随现有文件（`YYYY-MM-DD-主题.md` 或 `主题-YYYYMMDD.md`）；结论先行、数字可复核（写清 SQL / 命令）、失败和缺口也要写。
- 截图放 `docs/img/`，kebab-case 命名，文档里用相对链接引用。
- 大改动前后各跑一次 `db/check_data.py`，把 before / after 贴进报告。

## 9. 禁区

- 不给用药建议、不做剂量换算、不判断两种药能否互相替代（只引用 `collision` / `dose_warning` 的既有结论）。
- 不把俗称 / 旧名写进 `product_name`；不把 `collision` 视图改成手工标注结果。
- 不提交：`data/*.db`、`data/raw/`、`data/backups/`、`site/dist/`、`site/dist.zip`、`.env`、`tools/`、`.tmp/`、`.pylibs/`、`__pycache__/`。
- 不手工编辑 `site/dist/`（生成物）；不手工改 `gh-pages`。
- `.dsh/` 是本项目的 agent 配置（项目技能 + DSH 预设源），不参与站点构建；改 `.dsh/preset-drug/` 前先确认。

## 10. 代码风格

- Python 3.12，`from __future__ import annotations`，带 type hints，用 pathlib，docstring / print 用中文。
- 只读查询的数据库连接用 `mode=ro`（写法见 `tests/trilingual/run_tests.py`），避免误写库。
- 新脚本放对应目录（`etl/`、`db/`、`data/`、`lib/`、`site/`、`mobile/`）；若属于全量重建，接进 `run_all.py`。
- 站点 HTML / CSS / JS 由 `site/build.py` 内联生成；改样式或文案先搜现有常量，别另起一套。

## 11. 收尾

- 每次交付用一句话说清：改了什么 / 怎么验的 / 还剩什么。
- 没跑完的验证、已知缺口写进报告或 CHANGELOG 草稿，不要只留在对话里。
- 需要人类决策的事（许可、上线、花钱、删数据、改公开口径）先问，不要自己拍板。

## 附：项目技能

`.dsh/skills/` 下有四个项目技能，命中场景时用 `skill` 工具加载：

- `market-ingest` —— 接入新市场 / 重跑某国入库 / 数据源更新
- `site-build` —— 建站与验收（含三语抽查、性能回归、本地预览）
- `data-audit` —— 数据体检、覆盖率统计、写报告
- `release` —— 版本发布与回滚
