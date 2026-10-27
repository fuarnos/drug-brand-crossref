# inbox —— 手机看板的指令队列

这个目录是手机看板（`mobile/`）的运行时数据，**进 git、可追溯**，但不要手工编辑。

| 文件 | 谁写 | 内容 |
|---|---|---|
| `commands.jsonl` | 手机页面 / `mobile/queue.py` | 一行一条指令：`{"id","ts","text","source","ua"}` |
| `replies.jsonl` | `mobile/inbox.py` / agent | 一行一条回帖：`{"id","cmd","ts","status","text","source"}` |

- **append-only**：只追加，不改历史行，不删行。第一次有指令时这两个文件才会出现。
- **状态是推导出来的**：某条指令的状态 = 它最后一条回帖的 `status`（`pending` / `doing` / `done` / `blocked`），
  没有回帖就是 `pending`。所以「改状态」= 追加一条新回帖，不是改旧行。
- `inbox/.lock` 是跨进程写锁，已被 `.gitignore` 忽略。

agent 开工先跑：

```powershell
& $py mobile/inbox.py pending
& $py mobile/inbox.py done <cmd_id> "做完的说明（带 reports/ 路径）"
```

用法与安全边界见 [../docs/手机通道.md](../docs/手机通道.md)。
