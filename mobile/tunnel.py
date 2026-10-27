"""cloudflared 快速隧道：让手机在 4G / 外网也能打开手机看板。

不需要 Cloudflare 账号，也不用装驱动：下载一个 `cloudflared.exe` 到 `tools/cloudflared/`
（`tools/` 已 gitignore），起 `tunnel --url http://127.0.0.1:<port>`，拿到形如
`https://xxx-yyy.trycloudflare.com` 的公网地址。

用法（在项目根目录）：
    python mobile/tunnel.py --ensure              # 只下载/检查 cloudflared，不连隧道
    python mobile/tunnel.py --port 8787           # 起隧道并打印公网地址（Ctrl+C 结束）

被 mobile/server.py --tunnel 调用时用：
    proc, url = start_tunnel(port)

注意：
- 快速隧道的域名**每次启动都变**；进程常驻期间稳定。要长期固定地址得用命名隧道
  （Cloudflare 账号 + `cloudflared tunnel login`）或 Tailscale，见 docs/手机通道.md。
- 隧道是公网可解析地址，但页面本身有 token 校验；不要把带 `?k=` 的完整链接发到公开群。
- 只用标准库（本机 curl/Invoke-WebRequest 受 schannel 限制，下载走 urllib）。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = ROOT / "tools" / "cloudflared"
EXE = BIN_DIR / "cloudflared.exe"
URL_FILE = ROOT / ".tmp" / "mobile" / "last-url.txt"
# 官方 latest 重定向地址；大小约 55 MB。
DOWNLOAD_URL = ("https://github.com/cloudflare/cloudflared/releases/latest/download/"
                "cloudflared-windows-amd64.exe")
URL_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")


def _say(msg: str) -> None:
    """立即输出：输出被重定向到管道时 print() 会攒着，手机上就等不到地址。"""
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------- 下载

def ensure_cloudflared(quiet: bool = False) -> Path:
    """返回 cloudflared.exe 路径；没有就下载。失败抛 RuntimeError。"""
    if EXE.exists() and EXE.stat().st_size > 1_000_000:
        return EXE
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = EXE.with_suffix(".part")
    _say(f"第一次使用，下载 cloudflared（约 55 MB）→ {EXE}")
    req = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": "drug-brand-crossref/mobile"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, tmp.open("wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if not quiet and total:
                    pct = done * 100 // total
                    if pct % 10 == 0 and pct != getattr(ensure_cloudflared, "_last", -1):
                        ensure_cloudflared._last = pct  # type: ignore[attr-defined]
                        _say(f"  {pct:3d}%  {done / 1e6:.1f} / {total / 1e6:.1f} MB")
    except (urllib.error.URLError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"下载 cloudflared 失败：{exc}\n"
            "  可以手动下载后放到 tools/cloudflared/cloudflared.exe：\n"
            f"  {DOWNLOAD_URL}\n"
            "  或者不用隧道，手机只走局域网（同一 Wi-Fi）。"
        ) from exc
    if tmp.stat().st_size < 1_000_000:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("下载到的 cloudflared 文件太小，可能被网络中断；重跑一次即可。")
    tmp.replace(EXE)
    _say(f"已就绪：{EXE}")
    return EXE


def version() -> str:
    """cloudflared --version 的第一行；没装就返回空串。"""
    if not EXE.exists():
        return ""
    try:
        out = subprocess.run([str(EXE), "--version"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=20)
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else ""
    except (OSError, subprocess.SubprocessError):
        return ""


# ---------------------------------------------------------------- 隧道

def start_tunnel(port: int, on_url: Callable[[str], None] | None = None,
                 wait_seconds: float = 75.0) -> tuple[subprocess.Popen | None, str | None]:
    """起快速隧道，等到公网地址出现（或超时）后返回 (进程, 地址)。

    调用方负责在退出时 kill 进程；地址同时写入 .tmp/mobile/last-url.txt。
    """
    try:
        exe = ensure_cloudflared()
    except RuntimeError as exc:
        _say(f"！{exc}")
        return None, None

    cmd = [str(exe), "tunnel", "--url", f"http://127.0.0.1:{port}",
           "--no-autoupdate", "--protocol", "http2"]
    _say("正在连 Cloudflare 隧道…（首次约 5–15 秒）")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1)
    found: list[str] = []
    done = threading.Event()

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            if not found:
                m = URL_RE.search(line)
                if m:
                    found.append(m.group(0))
                    URL_FILE.parent.mkdir(parents=True, exist_ok=True)
                    URL_FILE.write_text(found[0], encoding="utf-8")
                    _say(f"公网地址：{found[0]}")
                    if on_url:
                        on_url(found[0])
                    done.set()
            if "--" in line and "ERR" in line.upper() and not found:
                _say(f"  cloudflared: {line.strip()[:160]}")

    threading.Thread(target=pump, daemon=True).start()
    done.wait(wait_seconds)
    if not found:
        _say("！没在限定时间内拿到公网地址；隧道进程保留，可看上面 cloudflared 输出。")
        return proc, None
    return proc, found[0]


def stop_tunnel(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------- 入口

def main() -> None:
    ap = argparse.ArgumentParser(description="cloudflared 快速隧道（手机 4G 访问）")
    ap.add_argument("--port", type=int, default=8787, help="本机手机看板端口（默认 8787）")
    ap.add_argument("--ensure", action="store_true", help="只下载/检查 cloudflared，不连隧道")
    args = ap.parse_args()

    if args.ensure:
        exe = ensure_cloudflared()
        _say(f"cloudflared：{exe}")
        _say(version() or "（版本号读不出来，但文件在）")
        return

    proc, url = start_tunnel(args.port)
    if not url:
        stop_tunnel(proc)
        raise SystemExit("隧道没起来。局域网仍可用；外网换用 ssh -R（见 docs/手机通道.md）。")
    token_file = ROOT / ".tmp" / "mobile" / "token.txt"
    if token_file.exists():
        _say(f"手机打开：{url}/?k={token_file.read_text(encoding='utf-8').strip()}")
    else:
        _say(f"手机打开：{url}/   （先起 mobile/server.py 才有 token）")
    _say("按 Ctrl+C 停止隧道。")
    try:
        while proc.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        _say("\n已停止隧道")
    finally:
        stop_tunnel(proc)


if __name__ == "__main__":
    sys.exit(main())
