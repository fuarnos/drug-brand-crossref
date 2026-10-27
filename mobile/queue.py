"""手机指令队列：append-only JSONL + 文件锁 + 状态推导。

对应 docs/手机通道-设计.md §3 / §4.1。两条文件只追加、不改历史行：

    inbox/commands.jsonl   手机 / 人下的指令
    inbox/replies.jsonl    agent / 人的回帖（用 cmd 字段指回指令）

**状态不落库**：某条指令的 status = 它最后一条回帖的 status，没有回帖就是 pending。
多进程同时写用 inbox/.lock（O_CREAT|O_EXCL 自旋）互斥，避免丢行和半行 JSON。

用法：

    from mobile import queue
    cmd = queue.append_command("把墨西哥浓度复核补完", ua="iPhone Safari")
    queue.append_reply(cmd["id"], "done", "已重跑，见 reports/mx-*.md")
    state = queue.load_state()      # {"commands": [...], "counts": {...}}
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parent.parent

# 队列目录：默认 <repo>/inbox；测试用环境变量 MOBILE_INBOX 覆盖（见 inbox_dir()）。
INBOX_DIR: Path = Path(os.environ.get("MOBILE_INBOX") or ROOT / "inbox")

STATUSES: tuple[str, ...] = ("pending", "doing", "done", "blocked")

COMMANDS_FILE = "commands.jsonl"
REPLIES_FILE = "replies.jsonl"
LOCK_FILE = ".lock"

MAX_TEXT = 2000        # 单条正文上限（字符数，与设计 §3 一致）
LOCK_TIMEOUT = 5.0     # 等锁上限（秒）
LOCK_POLL = 0.02       # 等锁自旋间隔（秒）
LOCK_STALE = 30.0      # 锁文件超过这么久没释放，视为死进程留下的


def inbox_dir() -> Path:
    """当前生效的队列目录：环境变量 MOBILE_INBOX 优先，其次模块常量 INBOX_DIR。"""
    raw = os.environ.get("MOBILE_INBOX")
    return Path(raw).expanduser() if raw else INBOX_DIR


def ensure_dirs() -> None:
    """确保队列目录存在（幂等；读操作不会调用它）。"""
    inbox_dir().mkdir(parents=True, exist_ok=True)


def _path(name: str, *, create: bool = False) -> Path:
    """队列文件的完整路径；create=True 时顺带建目录。"""
    directory = inbox_dir()
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory / name


def _now_ts() -> str:
    """本地时区 ISO 8601 时间戳（精确到秒）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _warn(message: str) -> None:
    """一行警告打到 stderr：坏行不能把整页弄成 500。"""
    print(f"警告：{message}", file=sys.stderr, flush=True)


def _warn_bad_line(path: Path, lineno: int, reason: Any) -> None:
    _warn(f"跳过无法解析的队列行 {path.name}:{lineno}（{reason}）")


def _clean_text(text: str, what: str = "指令内容") -> str:
    """去首尾空白并校验长度；不合格抛 ValueError。"""
    if not isinstance(text, str):
        raise ValueError(f"{what}必须是字符串")
    clean = text.strip()
    if not clean:
        raise ValueError(f"{what}不能为空")
    if len(clean) > MAX_TEXT:
        raise ValueError(f"{what}过长：{len(clean)} 字（上限 {MAX_TEXT} 字）")
    return clean


def _check_status(status: str) -> str:
    if status not in STATUSES:
        raise ValueError(f"非法状态：{status!r}（可选：{' / '.join(STATUSES)}）")
    return status


def _break_stale_lock(lock: Path) -> None:
    """锁文件超过 LOCK_STALE 秒视为死进程残留，删掉重试。

    不加这一步，一个被 kill 的进程会让队列永远卡在 TimeoutError 上。
    """
    try:
        mtime = lock.stat().st_mtime
    except FileNotFoundError:
        return
    age = time.time() - mtime
    if age <= LOCK_STALE:
        return
    try:
        lock.unlink()
    except OSError:
        return
    _warn(f"清理超时锁文件 {lock}（{age:.0f} 秒未释放）")


@contextlib.contextmanager
def _locked(*, timeout: float | None = None) -> Iterator[Path]:
    """拿 inbox/.lock 互斥写：O_CREAT|O_EXCL 自旋，超时抛 TimeoutError，退出时删锁。"""
    if timeout is None:
        timeout = LOCK_TIMEOUT
    lock = _path(LOCK_FILE, create=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            _break_stale_lock(lock)
        except OSError:
            # Windows 上别人正在删锁时可能报共享冲突，按「锁被占」处理，继续自旋。
            pass
        if time.monotonic() >= deadline:
            raise TimeoutError(f"队列锁等待超时（{timeout:g} 秒）：{lock}")
        time.sleep(LOCK_POLL)
    try:
        os.write(fd, f"{os.getpid()} {_now_ts()}\n".encode("ascii", "ignore"))
    finally:
        os.close(fd)
    try:
        yield lock
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


def _read_jsonl(
    path: Path,
    *,
    required: tuple[str, ...] = ("id", "ts"),
    validate: Callable[[dict], str | None] | None = None,
) -> list[dict]:
    """读一条 JSONL：坏行跳过并告警，其余照常返回。"""
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                _warn_bad_line(path, lineno, exc)
                continue
            if not isinstance(rec, dict):
                _warn_bad_line(path, lineno, "不是 JSON 对象")
                continue
            missing = [k for k in required if not isinstance(rec.get(k), str) or not rec.get(k)]
            if missing:
                _warn_bad_line(path, lineno, f"缺字段 {'/'.join(missing)}")
                continue
            if validate is not None:
                reason = validate(rec)
                if reason:
                    _warn_bad_line(path, lineno, reason)
                    continue
            out.append(rec)
    return out


def _append_line(path: Path, rec: dict) -> None:
    """追加一行 JSON（调用方必须持锁）。"""
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _existing_ids(path: Path) -> set[str]:
    """已用过的记录 id，用来保证同一秒内也不撞号。"""
    ids: set[str] = set()
    for rec in _read_jsonl(path, required=("id",)):
        ids.add(rec["id"])
    return ids


def _new_id(prefix: str, seen: set[str]) -> str:
    """生成 c-/r-YYYYMMDD-HHMMSS-4位hex 形式的 id（同一秒内自动避重）。"""
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    for _ in range(1000):
        candidate = f"{prefix}-{stamp}-{secrets.token_hex(2)}"
        if candidate not in seen:
            seen.add(candidate)
            return candidate
    raise RuntimeError("无法生成唯一 id：同一秒内尝试次数过多")


def _ts_key(rec: dict) -> tuple[int, float]:
    """按真实时间排序的 key；解析不了的 ts 排到最后（保持写入顺序）。"""
    raw = rec.get("ts")
    if isinstance(raw, str):
        try:
            moment = datetime.fromisoformat(raw)
        except ValueError:
            moment = None
        if moment is not None:
            if moment.tzinfo is None:
                moment = moment.astimezone()
            return (0, moment.timestamp())
    return (1, 0.0)


def append_command(text: str, *, source: str = "phone", ua: str = "") -> dict:
    """追加一条指令，返回完整记录（含 id / ts / source / ua）。"""
    clean = _clean_text(text, "指令内容")
    with _locked():
        path = _path(COMMANDS_FILE, create=True)
        rec = {
            "id": _new_id("c", _existing_ids(path)),
            "ts": _now_ts(),
            "text": clean,
            "source": source,
            "ua": ua,
        }
        _append_line(path, rec)
    return rec


def _check_reply(rec: dict) -> str | None:
    """回帖行校验：cmd 指向存在由 append_reply 管，这里只查自身字段。"""
    status = rec.get("status")
    if status not in STATUSES:
        return f"非法状态 {status!r}"
    if not isinstance(rec.get("cmd"), str) or not rec["cmd"]:
        return "缺字段 cmd"
    return None


def append_reply(cmd_id: str, status: str, text: str, *, source: str = "agent") -> dict:
    """给一条指令回帖，返回完整记录；cmd_id 不存在或参数非法抛 ValueError。"""
    clean = _clean_text(text, "回帖内容")
    _check_status(status)
    if not isinstance(cmd_id, str) or not cmd_id:
        raise ValueError("cmd_id 不能为空")
    with _locked():
        cmd_path = _path(COMMANDS_FILE, create=True)
        known = {rec["id"] for rec in _read_jsonl(cmd_path, required=("id",))}
        if cmd_id not in known:
            raise ValueError(f"回帖指向的指令不存在：{cmd_id}")
        path = _path(REPLIES_FILE, create=True)
        rec = {
            "id": _new_id("r", _existing_ids(path)),
            "cmd": cmd_id,
            "ts": _now_ts(),
            "status": status,
            "text": clean,
            "source": source,
        }
        _append_line(path, rec)
    return rec


def load_state() -> dict:
    """返回 {"commands": [...], "counts": {...}}，commands / replies 均按 ts 升序。

    每条指令带推导出来的 status 与它的 replies；没有回帖就是 pending。
    坏行跳过并告警，不抛异常。
    """
    commands = _read_jsonl(_path(COMMANDS_FILE))
    replies_raw = _read_jsonl(_path(REPLIES_FILE), validate=_check_reply)

    replies_by_cmd: dict[str, list[dict]] = {}
    for rec in replies_raw:
        replies_by_cmd.setdefault(rec["cmd"], []).append(rec)

    result: list[dict] = []
    for rec in commands:
        replies = sorted(replies_by_cmd.get(rec["id"], []), key=_ts_key)
        result.append({
            "id": rec["id"],
            "ts": rec["ts"],
            "text": rec.get("text") if isinstance(rec.get("text"), str) else "",
            "source": rec.get("source") if isinstance(rec.get("source"), str) else "",
            "ua": rec.get("ua") if isinstance(rec.get("ua"), str) else "",
            "status": replies[-1]["status"] if replies else "pending",
            "replies": replies,
        })
    result.sort(key=_ts_key)

    counts = {"total": len(result)}
    counts.update({status: 0 for status in STATUSES})
    for rec in result:
        counts[rec["status"]] += 1
    return {"commands": result, "counts": counts}
