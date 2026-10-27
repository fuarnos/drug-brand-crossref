"""手机通道：手机看进度 + 发指令。

模块：
    queue.py    append-only 指令队列（commands.jsonl / replies.jsonl）
    server.py   HTTP 服务（页面 + /api/state + /api/command）
    page.py     手机页面（内联 HTML/CSS/JS，无外链）
    inbox.py    agent 侧 CLI（pending / list / reply / done / blocked）
    tunnel.py   cloudflared 快速隧道（外网 / 4G 访问）

设计见 docs/手机通道-设计.md，用法见 docs/手机通道.md。
"""

from __future__ import annotations
