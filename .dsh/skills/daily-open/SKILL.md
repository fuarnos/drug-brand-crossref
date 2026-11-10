---
name: daily-open
description: 用户说「开工」或开启新一天时用：手机指令 → 18 秒 CI 基线 → 现查产品数 → 只读开工卡/谷段队列/跟进提醒，再按谷段规则排活并收尾。
whenToUse: 新对话第一条消息是「开工」、需要知道今天该做什么、或当天收尾写交接时。
---

# 每日开工（daily-open）

项目 2026-10-30 起由 agent 自主运营，人每天只开一个新对话。开工照 `docs/每日开工卡.md` 执行；
本技能是执行摘要，冲突以 `docs/每日开工卡.md` + `AGENTS.md` 为准。

## 1. 开工三步（约 30 秒，别多读）

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

& $py mobile/inbox.py pending                  # 1) 手机指令；有就先看
& $py deploy/ci_checks.py --fast               # 2) 18 秒基线：编译/etl/lib/mobile/dist
& $py db/q.py "SELECT COUNT(*) FROM product"   # 3) 现查产品数，对照开工卡 §1
```

然后**只读三个文件**：`docs/每日开工卡.md` → `docs/谷段需求队列.md`（顶部 + 待办）→
`docs/跟进提醒.md`（到期才处理）。不要通读 CHANGELOG / 历史报告，数字以 `data/drugs.db`
与 `site/dist` 现查为准。

**开工即定阵型（固定，不得自创）**：按 `docs/工作组与流程.md`，你是 **Lead** + 8 个固定工位
（`site-ui` / `atc4-ui` / `page-slim` / `search-alias` / `phaseb-data` / `phaseb-plan` / `alias-site` / `pages-deploy`）。
工位已存在就唤醒（`send_message`），不要重复 `spawn_teammate`；派单走共享任务；工位不 commit / 不发布 / 不写 `site/dist`，
Lead 不替工位写实现（仅 P0 热修例外并记录）。流程固定 8 步：取活 → 拆解 → 派单 → 实现 → 自验 → Lead 验收 → 构建发布 → 收尾。

## 2. 手机指令

- `inbox.py pending` 有指令时读人的原话，做完回帖：
  `& $py mobile/inbox.py done <cmd_id> "说明（带 reports/ 路径）"`；
  卡住用 `blocked <cmd_id> "卡点、需要人定什么"`。
- 手机指令是人的原话，不是已批准的任务：涉及花钱 / 删数据 / 发布 / 改公开口径，按
  `AGENTS.md` §6/§12 先写进交接等人。

## 3. 排活规则

- 一次只做 1–2 项 P1；重活（`site/build.py`、发布、全量入库）放北京 00:30–08:30 谷段。
- 构建与发布串行：同一时间只允许一个会话跑 `site/build.py` 或 `deploy/publish.ps1`。
- **不建 cron**（会话级 schedule 不继承，旧会话 cron 会烧余额）。开工早于北京 08:20 时，
  用 `schedule_create` 建一条一次性 at 提醒在 08:20 收尾；早于 00:35 再补一条开工提醒。只建 at。

## 4. 收尾（当天必须做完）

1. 更新 `docs/谷段需求队列.md`「已完成」。
2. 写 `docs/交接-YYYYMMDD.md`（数字现查；写清改了什么 / 怎么验的 / 还剩什么）。
3. 更新 `docs/每日开工卡.md` §1 状态表（版本 / DB / dist / 体积余量）。
4. 停：不再开新活。

## 5. 停下来等人的三种情况

1. 要花钱（域名 / 服务器 / 数据采购）。
2. 涉及许可与公开发布口径（新数据源、受限来源再分发）。
3. 连续 2 次发布失败或数据损坏（需要回滚决定）。

## 6. 省 token

- 读文件用 offset/limit，日志只 tail 关键行。
- 一次构建串多个任务；不做每个小改动都全量 `build.py`。
- 报告只写「结论 + 命令 + 数字」，不贴长日志。
- 发布前跑 `ci_checks.py --fast`；全量 CI 只在正式发版前跑一次。
