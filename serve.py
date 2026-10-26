"""本地预览：双击「打开网站.cmd」，或运行 python serve.py

为什么不能直接双击 site/dist/index.html：
浏览器不允许 file:// 页面读取本地 JSON 索引，页面会停在"正在加载索引"。
静态站本身没问题，是浏览器对本地文件的安全限制。

上线后由 Cloudflare Pages / GitHub Pages 直接托管同样的文件，不需要这个脚本。
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path

DIST = Path(__file__).resolve().parent / "site" / "dist"


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # 少刷屏
        pass

    def end_headers(self) -> None:
        # 本地开发别缓存，改了就能看到
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", type=int, default=8000)
    ap.add_argument("--open", action="store_true", help="起好后自动打开浏览器")
    args = ap.parse_args()

    index = DIST / "index.html"
    if not index.exists():
        raise SystemExit(f"还没构建：{index} 不存在。先跑 python site/build.py")

    handler = functools.partial(Handler, directory=str(DIST))
    httpd = None
    for port in range(args.port, args.port + 20):
        try:
            httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
            break
        except OSError:
            print(f"端口 {port} 被占用，换一个…")
    if httpd is None:
        raise SystemExit("找不到可用端口")

    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"站点目录：{DIST}")
    print(f"打开这个地址：{url}")
    print("关掉这个窗口就停止服务。")
    if args.open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
