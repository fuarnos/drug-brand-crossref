"""手机通道 HTTP 服务：看进度 + 往指令队列追加一句话。

契约见 docs/手机通道-设计.md §4.3：

    GET  /               200 手机页面（需 token）｜401
    GET  /api/state      200 {"ok":true,"queue":...,"progress":{...},"server":{...}}（需 token）
    POST /api/command    {"text":"..."} -> 201 {"ok":true,"id":"c-..."}（需 token）
    GET  /healthz        200 "ok"（免 token）
    其他路径             404

token：--token > 环境变量 MOBILE_TOKEN > .tmp/mobile/token.txt > 自动生成并写回该文件。
队列只通过 mobile/queue.py 读写；data/drugs.db 只读，不提供任何写库 / 入库路径。

用法（项目根目录）：

    python mobile/server.py                     # 局域网 0.0.0.0:8787
    python mobile/server.py --port 8788 --open  # 换端口并打开本机浏览器
    python mobile/server.py --tunnel            # 另起 cloudflared 快速隧道（4G 访问）

退出：Ctrl+C 或关掉窗口。
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from datetime import datetime
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mobile.page import render_denied, render_index  # noqa: E402
from mobile.queue import append_command, load_state  # noqa: E402
from render_dashboard import db_stats, dist_stats  # noqa: E402

TOKEN_FILE = ROOT / ".tmp" / "mobile" / "token.txt"
PROGRESS_FILE = ROOT / ".tmp" / "mobile" / "progress.json"
CHANGELOG = ROOT / "CHANGELOG.md"
DB_PATH = ROOT / "data" / "drugs.db"
DIST = ROOT / "site" / "dist"
REPORTS = ROOT / "reports"
GIT_EXE = ROOT / "tools" / "git" / "cmd" / "git.exe"

COOKIE_NAME = "mb_token"
COOKIE_MAX_AGE = 2_592_000  # 30 天
RATE_LIMIT = 20             # 同 IP 每分钟最多 POST 次数
RATE_WINDOW = 60.0
MAX_TEXT = 2_000            # 单条指令正文上限（字）
MAX_BODY = 64 * 1024        # 请求体硬上限（字节）
SCAN_SECONDS = 60.0         # 后台每 60 秒检查一次源数据有没有变
STALE_SECONDS = 600.0       # 快照超过 10 分钟就算「过期」
BUILDING_WINDOW = 90.0      # dist/index.html 这么新 -> 可能正在建站

DB_KEYS = ("total", "subst", "keys", "named", "severe", "warn", "info",
           "US", "GB", "CN", "ES", "MX", "AU", "CA")
VERSION_RE = re.compile(r"^##\s+(v[0-9][^\s]*)\s*[—–-]\s*(\d{4}-\d{2}-\d{2})", re.M)


# ---------------------------------------------------------------- token

def load_token(explicit: str | None = None) -> tuple[str, str]:
    """返回 (token, 来源说明)。

    优先级：--token > 环境变量 MOBILE_TOKEN > .tmp/mobile/token.txt > 自动生成并写回。
    """
    if explicit:
        return explicit, "命令行 --token"
    env = os.environ.get("MOBILE_TOKEN", "").strip()
    if env:
        return env, "环境变量 MOBILE_TOKEN"
    try:
        cached = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        cached = ""
    if cached:
        return cached, f"沿用 {TOKEN_FILE}"
    token = secrets.token_urlsafe(18)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token, f"新建并写入 {TOKEN_FILE}"


def local_ipv4() -> str:
    """尽力探测本机内网 IPv4；失败就退回 127.0.0.1。"""
    probes = (("192.168.1.1", 80), ("10.0.0.1", 80))
    for host, port in probes:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((host, port))  # UDP connect 不发包，只让内核选出口地址
                ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            continue
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return "127.0.0.1"


# ---------------------------------------------------------------- 进度

def read_release() -> tuple[str, str]:
    """CHANGELOG.md 第一条 `## vX — YYYY-MM-DD`；解析不到返回空串。"""
    try:
        text = CHANGELOG.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    match = VERSION_RE.search(text)
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def _progress_mtimes() -> tuple[float, float]:
    """快照对应源文件的 mtime：库文件 + 站点入口页。"""
    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0
    return mtime(DB_PATH), mtime(DIST / "index.html")


def _build_progress() -> dict[str, Any]:
    version, version_date = read_release()
    return {
        "db": _db_progress(),
        "site": _site_progress(),
        "repo": _repo_progress(version, version_date),
        "reports": _recent_reports(5),
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _db_progress() -> dict[str, int]:
    """复用看板口径：render_dashboard.db_stats()，只投影设计里约定的字段。"""
    try:
        raw = db_stats()
    except Exception as exc:  # 统计失败不能让整页 500
        print(f"！读取数据库进度失败：{exc}")
        raw = {}
    return {key: int(raw.get(key, 0) or 0) for key in DB_KEYS}


def _site_progress() -> dict[str, Any]:
    """复用 render_dashboard.dist_stats()；构建时间另从 dist/index.html 的 mtime 推。"""
    try:
        raw = dist_stats()
    except Exception as exc:
        print(f"！读取站点进度失败：{exc}")
        raw = {}

    built_at = ""
    age_min: int | None = None
    building = False
    entry = DIST / "index.html"
    try:
        mtime = entry.stat().st_mtime
    except OSError:
        mtime = None
    if mtime is not None:
        age = max(0.0, time.time() - mtime)
        built_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        age_min = int(age // 60)
        building = age <= BUILDING_WINDOW

    return {
        "built_at": built_at,
        "files": int(raw.get("files", 0) or 0),
        "index_mb": round(int(raw.get("index", 0) or 0) / 1e6, 1),
        "drug": int(raw.get("drug", 0) or 0),
        "name": int(raw.get("name", 0) or 0),
        "age_min": age_min,
        "building": building,
    }


def _git(*args: str) -> str | None:
    """跑一条只读 git 命令；失败（没装 / 不是仓库 / 超时）返回 None。"""
    exe = str(GIT_EXE) if GIT_EXE.exists() else (shutil.which("git") or "")
    if not exe:
        return None
    cmd = [exe, "-c", "core.quotepath=false", "-c", "core.abbrev=7",
           "--no-optional-locks", *args]
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=8)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _repo_progress(version: str, version_date: str) -> dict[str, Any]:
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or ""
    head = _git("log", "-1", "--date=short", "--format=%h %ad %s") or ""
    if len(head) > 90:
        head = head[:89] + "…"
    status = _git("status", "--porcelain")
    dirty = None if status is None else len([line for line in status.splitlines() if line.strip()])
    return {
        "branch": branch,
        "head": head,
        "dirty": dirty,
        "version": version,
        "version_date": version_date,
    }


def _recent_reports(limit: int) -> list[dict[str, str]]:
    """reports/*.md 按 mtime 取最新几条。"""
    try:
        paths = [path for path in REPORTS.glob("*.md") if path.is_file()]
        paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return []
    out: list[dict[str, str]] = []
    for path in paths[:limit]:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        out.append({"name": path.name,
                    "mtime": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")})
    return out


# ---------------------------------------------------------------- 快照

class ProgressStore:
    """进度快照：内存 + .tmp/mobile/progress.json，后台线程算，请求只读。

    db_stats() 冷 / 热都要约 7 秒，dist_stats() 逐文件 stat 约 5 秒，
    所以 /api/state 绝不同步计算：先返回旧快照（或 warming），后台再刷新。
    """

    def __init__(self, path: Path = PROGRESS_FILE) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._computing = False
        self._force = False
        self._wake = threading.Event()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._load()

    # -------------------------------------------------------- 对外

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="mobile-progress", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        self._wake.set()

    def trigger(self, force: bool = True) -> None:
        """叫后台算一次；force=True 时忽略 mtime 是否变化。"""
        if force:
            self._force = True
        self._wake.set()

    def state(self) -> dict[str, Any]:
        with self._lock:
            snapshot = self._snapshot
            computing = self._computing
        if snapshot is None:
            return {"progress": None, "computed_at": None, "stale": True,
                    "warming": True, "refreshing": computing}
        computed_at = str(snapshot.get("computed_at", ""))
        try:
            age = (datetime.now() - datetime.fromisoformat(computed_at)).total_seconds()
        except ValueError:
            age = STALE_SECONDS + 1
        return {"progress": snapshot.get("payload"),
                "computed_at": computed_at,
                "stale": age > STALE_SECONDS,
                "warming": False,
                "refreshing": computing}

    # -------------------------------------------------------- 内部

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if (isinstance(data, dict) and isinstance(data.get("payload"), dict)
                and isinstance(data.get("computed_at"), str)):
            self._snapshot = data

    def _write(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)  # 原子替换：读的一方不会看到半截 JSON

    def _loop(self) -> None:
        self._compute(force=True)  # 启动先算一次；期间请求读旧快照 / warming
        while not self._stopped.is_set():
            self._wake.wait(SCAN_SECONDS)
            self._wake.clear()
            if self._stopped.is_set():
                break
            force = self._force
            self._force = False
            self._compute(force=force)

    def _compute(self, force: bool) -> None:
        db_mtime, dist_mtime = _progress_mtimes()
        with self._lock:
            snapshot = self._snapshot
            self._computing = True
        try:
            if (not force and snapshot is not None
                    and float(snapshot.get("db_mtime", -1.0)) == db_mtime
                    and float(snapshot.get("dist_mtime", -1.0)) == dist_mtime):
                return
            payload = _build_progress()
            record = {
                "computed_at": datetime.now().isoformat(timespec="seconds"),
                "db_mtime": db_mtime,
                "dist_mtime": dist_mtime,
                "payload": payload,
            }
            self._write(record)
            with self._lock:
                self._snapshot = record
        except Exception as exc:
            print(f"！后台统计进度失败：{exc}")
            traceback.print_exc()
        finally:
            with self._lock:
                self._computing = False


# ---------------------------------------------------------------- 限流

class _RateLimiter:
    """按 IP 的滑动窗口限流；进程内即可（本机 / 单隧道场景）。"""

    def __init__(self, limit: int = RATE_LIMIT, window: float = RATE_WINDOW) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            if len(self._hits) > 256:  # 防止长时间运行后字典无限长
                self._hits = {k: v for k, v in self._hits.items()
                              if v and now - v[-1] < self.window}
            return True


# ---------------------------------------------------------------- 服务

class MobileServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], token: str) -> None:
        self.token = token
        self.started_at = time.time()
        self.started_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.limiter = _RateLimiter()
        self.progress = ProgressStore()
        super().__init__(server_address, MobileHandler)
        self.progress.start()

    def server_close(self) -> None:
        self.progress.stop()
        super().server_close()


class MobileHandler(BaseHTTPRequestHandler):
    server: MobileServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """每 20 秒轮询一次，默认访问日志太吵；启动信息在 main() 里已经打印。"""
        return

    # ------------------------------------------------------------ 路由

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._handle_get()
        except Exception:
            traceback.print_exc()
            self._send_json(500, {"ok": False, "error": "服务端出错，看启动窗口的报错。"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._handle_post()
        except Exception:
            traceback.print_exc()
            self._send_json(500, {"ok": False, "error": "服务端出错，看启动窗口的报错。"})

    def _handle_get(self) -> None:
        path, key, query = self._parse()
        if path == "/healthz":
            self._send_bytes(200, b"ok", "text/plain; charset=utf-8")
            return

        # 带 ?k= 的链接：命中就种 cookie 并 302 到干净地址；不命中一律 401。
        if key is not None:
            if self._token_ok(key):
                self._redirect_to_root()
            else:
                self._send_denied()
            return
        if not self._token_ok(self._cookie_token()):
            self._send_denied()
            return

        if path == "/":
            version, _ = read_release()
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            self._send_html(200, render_index(version, now))
        elif path == "/api/state":
            fresh = (query.get("fresh") or [""])[0] in ("1", "true", "yes")
            self._send_json(200, self._state_payload(fresh))
        else:
            self._send_not_found()

    def _handle_post(self) -> None:
        path, key, _ = self._parse()
        if path != "/api/command":
            self._send_not_found()
            return

        supplied = key if key is not None else self._cookie_token()
        if not self._token_ok(supplied):
            self._send_denied()
            return

        ip = str(self.client_address[0])
        if not self.server.limiter.allow(ip):
            self._send_json(429, {"ok": False, "error": "请求太频繁：每分钟最多 20 条，请稍后再试。"},
                            extra_headers={"Retry-After": "60"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0:
            self._send_json(400, {"ok": False, "error": "正文为空"})
            return
        if length > MAX_BODY:
            self._send_json(413, {"ok": False, "error": "正文太大"})
            return

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"ok": False, "error": "正文不是合法 JSON"})
            return
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str):
            self._send_json(400, {"ok": False, "error": "缺少 text 字段"})
            return
        text = text.strip()
        if not text:
            self._send_json(400, {"ok": False, "error": "正文不能为空"})
            return
        if len(text) > MAX_TEXT:
            self._send_json(400, {"ok": False, "error": f"正文超过 {MAX_TEXT} 字"})
            return

        ua = (self.headers.get("User-Agent") or "")[:200]
        try:
            record = append_command(text, source="phone", ua=ua)
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(201, {"ok": True, "id": str(record.get("id", ""))})

    def _state_payload(self, fresh: bool = False) -> dict[str, Any]:
        if fresh:
            self.server.progress.trigger(force=True)
        payload: dict[str, Any] = {
            "ok": True,
            "queue": load_state(),  # 队列很小，每次现读，不进快照
        }
        payload.update(self.server.progress.state())
        payload["server"] = {
            "started": self.server.started_text,
            "uptime_sec": int(time.time() - self.server.started_at),
        }
        if fresh:
            payload["refreshing"] = True
        return payload

    # ------------------------------------------------------------ token

    def _parse(self) -> tuple[str, str | None, dict[str, list[str]]]:
        parts = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        values = query.get("k")
        return parts.path, (values[0] if values else None), query

    def _token_ok(self, supplied: str | None) -> bool:
        if not supplied:
            return False
        return hmac.compare_digest(supplied, self.server.token)

    def _cookie_token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = SimpleCookie()
        try:
            jar.load(raw)
        except CookieError:
            return None
        morsel = jar.get(COOKIE_NAME)
        return morsel.value if morsel else None

    # ------------------------------------------------------------ 响应

    def _send_bytes(self, status: int, body: bytes, content_type: str,
                    extra_headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, status: int, payload: dict[str, Any],
                   extra_headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8", extra_headers)

    def _send_html(self, status: int, text: str) -> None:
        self._send_bytes(status, text.encode("utf-8"), "text/html; charset=utf-8")

    def _send_denied(self) -> None:
        self._send_html(401, render_denied())

    def _send_not_found(self) -> None:
        self._send_bytes(404, "404 not found".encode("utf-8"), "text/plain; charset=utf-8")

    def _redirect_to_root(self) -> None:
        cookie = SimpleCookie()
        cookie[COOKIE_NAME] = self.server.token
        morsel = cookie[COOKIE_NAME]
        morsel["httponly"] = True
        morsel["samesite"] = "Lax"
        morsel["path"] = "/"
        morsel["max-age"] = str(COOKIE_MAX_AGE)
        self._send_bytes(302, b"", "text/plain; charset=utf-8", {
            "Location": "/",
            "Set-Cookie": morsel.OutputString(),
        })


def make_server(host: str = "0.0.0.0", port: int = 8787, token: str = "") -> MobileServer:
    """建服务但不 serve；测试可传 127.0.0.1:0 拿随机端口。"""
    return MobileServer((host, int(port)), token)


# ---------------------------------------------------------------- 入口

def main() -> None:
    parser = argparse.ArgumentParser(
        description="手机看板：看进度 + 发指令（只读数据，不写库）")
    parser.add_argument("--host", default="0.0.0.0",
                        help="监听地址（默认 0.0.0.0，手机同 Wi-Fi 可访问）")
    parser.add_argument("--port", type=int, default=8787, help="端口（默认 8787）")
    parser.add_argument("--token", default=None,
                        help="访问 token（默认 MOBILE_TOKEN / .tmp/mobile/token.txt / 自动生成）")
    parser.add_argument("--open", action="store_true", dest="open_browser",
                        help="启动后用本机浏览器打开")
    parser.add_argument("--tunnel", action="store_true",
                        help="另起 cloudflared 快速隧道，供 4G / 外网访问")
    args = parser.parse_args()

    token, token_source = load_token(args.token)
    try:
        server = make_server(args.host, args.port, token)
    except OSError as exc:
        print(f"！端口 {args.port} 起不来：{exc}")
        print("  换一个端口再试：python mobile/server.py --port 8788")
        raise SystemExit(1) from exc

    port = int(server.server_address[1])
    lan_ip = local_ipv4()
    local_url = f"http://127.0.0.1:{port}/?k={token}"
    lan_url = f"http://{lan_ip}:{port}/?k={token}"

    print("手机通道已启动", flush=True)
    print(f"  token 来源：{token_source}", flush=True)
    print(f"  内网（手机同 Wi-Fi）：{lan_url}", flush=True)
    if lan_ip == "127.0.0.1":
        print("  ！没探测到内网 IPv4；手机可能打不开，可用 ipconfig 查地址后重试。", flush=True)
    print(f"  本机：{local_url}", flush=True)
    print("  关掉这个窗口 / Ctrl+C 即停止。", flush=True)
    print("  只读 data/drugs.db 与 site/dist；不给用药建议、不做剂量换算。", flush=True)

    if args.open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}/?k={token}")

    tunnel_proc = None
    tunnel_stop = None
    if args.tunnel:
        # TODO: 由 Lead 接 mobile/tunnel.py；这里只起线程、打印地址、退出时收尾。
        try:
            from mobile.tunnel import start_tunnel, stop_tunnel as tunnel_stop
        except Exception as exc:
            print(f"！隧道模块不可用：{exc}（局域网地址仍可用）", flush=True)
        else:
            def run_tunnel() -> None:
                nonlocal tunnel_proc
                try:
                    proc, url = start_tunnel(port)
                except Exception as exc:  # 隧道失败不影响局域网
                    print(f"！隧道启动失败：{exc}（局域网地址仍可用）", flush=True)
                    return
                tunnel_proc = proc
                if url:
                    print(f"手机（外网）：{url}/?k={token}", flush=True)
                else:
                    print("！隧道没起来，局域网地址仍可用。", flush=True)

            threading.Thread(target=run_tunnel, name="mobile-tunnel", daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止…")
    finally:
        server.server_close()
        if tunnel_proc is not None and tunnel_stop is not None:
            try:
                tunnel_stop(tunnel_proc)
            except Exception:
                pass
        print("已停止。")


if __name__ == "__main__":
    main()
