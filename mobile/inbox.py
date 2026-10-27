#!/usr/bin/env python
"""agent 侧指令队列 CLI：看待办、回帖，中文输出、宽度 ≤100 列。

对应 docs/手机通道-设计.md §4.4。典型用法：

    python mobile/inbox.py pending                       # 开工先跑：列未处理指令
    python mobile/inbox.py list [--all] [--limit 20]     # 最新在前，看处理历史
    python mobile/inbox.py reply <cmd_id> "已改完，见 reports/x.md" [--status done]
    python mobile/inbox.py done <cmd_id> "..."           # = reply --status done
    python mobile/inbox.py blocked <cmd_id> "..."        # 卡住了，等人决定

只读队列、只追加回帖，不编辑历史行；不会写 inbox/ 以外的任何东西。
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mobile import queue  # noqa: E402

WIDTH = 100  # 输出最大显示列宽（CJK 按 2 列算）

BADGE = {
    "pending": "[待办]",
    "doing": "[处理中]",
    "done": "[完成]",
    "blocked": "[受阻]",
}
SOURCE_ZH = {"phone": "手机", "agent": "agent", "cli": "命令行"}


# ---------------------------------------------------------------------------
# 排版：按显示宽度折行（中文没有空格，只能逐字断；英文按词断）
# ---------------------------------------------------------------------------

def _cell(ch: str) -> int:
    """单个字符占几列：CJK 全角 2 列，组合符 0 列，其余 1 列。"""
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _width(text: str) -> int:
    """一行文字占多少显示列。"""
    return sum(_cell(ch) for ch in text)


def _units(text: str) -> list[str]:
    """切成折行单元：连续 ASCII 词算一个，CJK / 空格逐字。"""
    units: list[str] = []
    buf = ""
    for ch in text:
        if ch.isascii() and not ch.isspace():
            buf += ch
        else:
            if buf:
                units.append(buf)
                buf = ""
            units.append(ch)
    if buf:
        units.append(buf)
    return units


def _wrap(text: str, width: int = WIDTH) -> list[str]:
    """把一段文字折成不超过 width 列的多行（保留原有换行）。"""
    width = max(4, width)
    lines: list[str] = []
    for para in str(text).splitlines() or [""]:
        cur, cur_w = "", 0
        for unit in _units(para):
            unit_w = _width(unit)
            if unit_w > width:  # 超长不可断的词/URL：硬切
                if cur:
                    lines.append(cur.rstrip())
                    cur, cur_w = "", 0
                piece = ""
                for ch in unit:
                    if piece and _width(piece) + _cell(ch) > width:
                        lines.append(piece)
                        piece = ""
                    piece += ch
                cur, cur_w = piece, _width(piece)
                continue
            if unit.isspace():
                if cur:
                    cur += unit
                    cur_w += unit_w
                continue
            if cur and cur_w + unit_w > width:
                lines.append(cur.rstrip())
                cur, cur_w = "", 0
            cur += unit
            cur_w += unit_w
        lines.append(cur.rstrip())
    return lines


def _indent(text: str, indent: int = 4) -> list[str]:
    """折行后整体缩进；空行不补空格。"""
    pad = " " * indent
    return [(pad + line) if line else "" for line in _wrap(text, WIDTH - indent)]


def _fmt_ts(ts: str) -> str:
    """ISO 时间戳 → 给人看的本地时间（精确到分）。"""
    try:
        moment = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return str(ts)[:16]
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


_BADGE_WIDTH = max(_width(badge) for badge in BADGE.values())


def _badge(status: str) -> str:
    """状态徽章，补空格对齐（[待办] 比 [处理中] 窄）。"""
    text = BADGE.get(status, "[?]")
    return text + " " * max(0, _BADGE_WIDTH - _width(text))


def _clip(text: str, width: int) -> str:
    """截断到 width 列，超出加省略号。"""
    if _width(text) <= width:
        return text
    out = ""
    for ch in text:
        if _width(out) + _cell(ch) > width - 1:
            break
        out += ch
    return out + "…"


def _source_text(cmd: dict) -> str:
    """来源 + UA 的短说明（UA 太长就截断）。"""
    src = cmd.get("source") or "phone"
    label = SOURCE_ZH.get(src, src)
    ua = (cmd.get("ua") or "").strip()
    if ua:
        return f"{label} · {_clip(ua, 24)}"
    return label


def _counts_line(counts: dict) -> str:
    return " · ".join(f"{BADGE[s]} {counts.get(s, 0)}" for s in queue.STATUSES)


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def _render_command(cmd: dict) -> list[str]:
    """一条指令 + 它的回帖。"""
    head = f"{_badge(cmd.get('status', ''))} {_fmt_ts(cmd.get('ts', ''))}  {cmd.get('id', '')}"
    source = _source_text(cmd)
    if source:
        head += f"  {source}"
    lines = [head]
    lines += _indent(cmd.get("text", ""))
    for reply in cmd.get("replies", []):
        prefix = f"→ {_fmt_ts(reply.get('ts', ''))} {_badge(reply.get('status', ''))} "
        body = prefix + (reply.get("text") or "")
        lines += _indent(body)
    return lines


def _print_commands(commands: list[dict]) -> None:
    for index, cmd in enumerate(commands):
        if index:
            print()
        print("\n".join(_render_command(cmd)))


def _reply_hint() -> str:
    return '回帖：python mobile/inbox.py done <cmd_id> "做完的说明"'


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

def cmd_pending(_args: argparse.Namespace) -> int:
    """只列未处理（pending）的指令，最早的在最前面。"""
    state = queue.load_state()
    counts = state["counts"]
    pending = [c for c in state["commands"] if c["status"] == "pending"]
    if not pending:
        print("没有待办指令")
        if counts.get("doing"):
            print(f"另有 {counts['doing']} 条 [处理中]，用 list --all 查看")
        return 0
    print(f"待办 {len(pending)} 条 · 队列共 {counts['total']} 条：{_counts_line(counts)}")
    _print_commands(pending)
    print()
    print(_reply_hint())
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """列指令：默认最新 20 条（新→旧），--all 看全部。"""
    state = queue.load_state()
    counts = state["counts"]
    if not state["commands"]:
        print("队列还是空的（手机发指令后会出现在这里）")
        return 0
    newest_first = list(reversed(state["commands"]))
    shown = newest_first if args.all else newest_first[: max(1, args.limit)]
    scope = f"最新 {len(shown)} / 共 {counts['total']} 条" if len(shown) < counts["total"] \
        else f"共 {counts['total']} 条"
    print(f"{scope}（新→旧）：{_counts_line(counts)}")
    _print_commands(shown)
    if len(shown) < counts["total"]:
        print()
        print(f"只显示最新 {len(shown)} 条，看全部用 list --all")
    return 0


def _do_reply(cmd_id: str, text: str, status: str) -> int:
    try:
        queue.append_reply(cmd_id, status, text, source="agent")
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except TimeoutError as exc:
        print(f"错误：{exc}（正在有人写队列，稍后重试）", file=sys.stderr)
        return 3
    print(f"已回帖：{cmd_id} → {status}")
    return 0


def cmd_reply(args: argparse.Namespace) -> int:
    return _do_reply(args.cmd_id, " ".join(args.text), args.status)


def cmd_done(args: argparse.Namespace) -> int:
    return _do_reply(args.cmd_id, " ".join(args.text), "done")


def cmd_blocked(args: argparse.Namespace) -> int:
    return _do_reply(args.cmd_id, " ".join(args.text), "blocked")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inbox.py",
        description="手机指令队列：看待办、回帖（数据在 inbox/*.jsonl，只追加不改历史）",
    )
    sub = parser.add_subparsers(dest="action")

    sub.add_parser("pending", help="列出未处理的指令（默认动作）")

    p_list = sub.add_parser("list", help="列指令，最新在前")
    p_list.add_argument("--all", action="store_true", help="显示全部（忽略 --limit）")
    p_list.add_argument("--limit", type=int, default=20, metavar="N", help="最多显示 N 条（默认 20）")

    p_reply = sub.add_parser("reply", help="给一条指令回帖")
    p_reply.add_argument("cmd_id", help="指令 id（c-YYYYMMDD-HHMMSS-xxxx）")
    p_reply.add_argument("text", nargs="+", help="回帖正文")
    p_reply.add_argument("--status", default="done", choices=queue.STATUSES,
                         help="回帖状态（默认 done）")

    p_done = sub.add_parser("done", help="回帖：已完成")
    p_done.add_argument("cmd_id")
    p_done.add_argument("text", nargs="+")

    p_blocked = sub.add_parser("blocked", help="回帖：卡住了，等人决定")
    p_blocked.add_argument("cmd_id")
    p_blocked.add_argument("text", nargs="+")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    action = args.action or "pending"
    handlers = {
        "pending": cmd_pending,
        "list": cmd_list,
        "reply": cmd_reply,
        "done": cmd_done,
        "blocked": cmd_blocked,
    }
    return handlers[action](args)


if __name__ == "__main__":
    raise SystemExit(main())
