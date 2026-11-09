"""同色守卫：任何嵌套表面的填充色，不许等于它所在容器的填充色。

规则来源（用户 2026-11-10 硬规则）：
    「框内颜色和框外颜色不许能一致」—— 面板里的输入框、下拉面板、卡片里的筛选区、
    chip、次要按钮，自身填充色不许等于最近一层不透明祖先容器的填充色；
    只靠一条 0.8px 边框区分不算合格。

做法：真浏览器（本机 Chrome + CDP，无 Playwright 依赖），两个视口各扫一遍，
对每个可见元素取 `background-color`（alpha ≥ 0.5），向上找最近的**不透明**祖先填充色，
两者 RGB 相同即记为违规（`#fff` 与 `rgb(255,255,255)` 视为同色）。

用法：
    python deploy/ui_surface_check.py                     # 扫 site/dist（脚本内置静态服务）
    python deploy/ui_surface_check.py --dist .tmp/dist-x   # 扫别的产物目录
    python deploy/ui_surface_check.py --base-url http://127.0.0.1:8001/   # 扫已起的服务
    python deploy/ui_surface_check.py --json .tmp/ui-surface/after.json   # 落 JSON
    python deploy/ui_surface_check.py --allow .tmp/ui-surface/allow.txt   # 白名单（正则，默认空）
    python deploy/ui_surface_check.py --shots docs/img    # 顺带留 4 张截图（首页/成分页 × 两视口）

退出码：0 = 无违规（含 SKIP）；1 = 有违规。
SKIP 的两种情况（都返回 0，只在输出里写明）：找不到本机 Chrome、产物目录不存在。

只读：被服务的文件一律只读打开，Chrome 用户目录放系统临时目录。
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = ROOT / "site" / "dist"

# 两个视口：桌面 / 手机（手机窄到 390 才会命中 @media(max-width:767px) 的那一整套布局）
VIEWPORTS = [(1280, 900, "1280x900"), (390, 844, "390x844")]

# 页面清单：(短名, 候选相对路径, 是否需要留截图)
# 后四项带 fallback：产物里没有 5 级 ATC 页 / 没有单一名页时退到真实存在的同类页，避免整轮 SKIP。
# 目标元素的尺寸、填充色另见 reports/v0102-ui-surface-20261110.md 的前后对照表。
PAGES: list[tuple[str, list[str], bool]] = [
    ("home", ["index.html"], True),
    ("results", ["index.html?q=%E6%B3%B0%E8%AF%BA&lang=zh"], False),
    ("drug", ["drug/acetaminophen.html"], True),
    ("name", ["name/tylenol.html", "name/tylenol-8-hr-arthritis-pain.html"], False),
    ("atc", ["atc/N02BE01.html", "atc/N02BE.html"], False),
    ("coverage", ["coverage.html"], False),
]

# 不参与判定的标签：不渲染背景，或由 UA 自己画。
SKIP_TAGS = (
    "script", "style", "link", "meta", "head", "title", "br", "hr", "template",
    "iframe", "img", "svg", "path", "option", "optgroup", "canvas", "source",
)
# 表单控件里这几类由 UA 绘制、没有「CSS 填充」概念，判同色只会产生假阳性；
# input[type=text]/select/textarea 照常参与判定（「槽里的输入框」正是要抓的）。
SKIP_INPUT_TYPES = ("checkbox", "radio", "range", "color", "file", "hidden")

CHROME_ENV_HINTS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)

# ── 采集 JS ─────────────────────────────────────────────────────────────────
# 返回 JSON 字符串：[{sel, own, ancSel, ancFill, w, h}]（已按 sel+own+ancSel 去重并计数）
SCAN_JS = r"""(function(){
  var SKIP_TAGS = %(skip_tags)s;
  var SKIP_TYPES = %(skip_types)s;
  function parseColor(c){
    if(!c) return null;
    if(c==='transparent') return {r:0,g:0,b:0,a:0};
    var m=/^rgba?\(([^)]*)\)$/.exec(c);
    if(!m) return null;
    var p=m[1].split(/[,/]+/).map(function(s){return s.trim();}).filter(function(s){return s!=='';});
    if(p.length<3) return null;
    var r=parseFloat(p[0]),g=parseFloat(p[1]),b=parseFloat(p[2]);
    var a=p.length>3?parseFloat(p[3]):1;
    if(isNaN(r)||isNaN(g)||isNaN(b)) return null;
    if(isNaN(a)) a=1;
    return {r:Math.round(r),g:Math.round(g),b:Math.round(b),a:a};
  }
  function sel(el){
    var t=el.tagName.toLowerCase();
    if(el.id) return t+'#'+el.id;
    var raw=(typeof el.className==='string'?el.className:'');
    var cls=raw.trim()?raw.trim().split(/\s+/).filter(Boolean).slice(0,3):[];
    return t+(cls.length?'.'+cls.join('.'):'');
  }
  function effOpacity(el){
    var op=1,n=el;
    while(n && n.nodeType===1){
      var o=parseFloat(getComputedStyle(n).opacity);
      if(!isNaN(o)) op*=o;
      n=n.parentElement;
    }
    return op;
  }
  var seen={}, out=[], total=0, all=document.querySelectorAll('body *');
  // 页面层（chrome）：页头 / 底栏与页面画布刻意同色（色阶第 1 层），不参与比较。
  function pageLayer(el){
    var t=el.tagName.toLowerCase();
    if(t==='header'||t==='body'||t==='html') return true;
    var c=(typeof el.className==='string'?el.className:'');
    return /(^|\s)tabbar(\s|$)/.test(c);
  }
  for(var i=0;i<all.length;i++){
    var el=all[i];
    var tag=el.tagName.toLowerCase();
    if(SKIP_TAGS.indexOf(tag)>=0) continue;
    if(tag==='input' && SKIP_TYPES.indexOf((el.type||'').toLowerCase())>=0) continue;
    if(pageLayer(el)) continue;
    var cs=getComputedStyle(el);
    if(cs.display==='none'||cs.visibility==='hidden'||cs.visibility==='collapse') continue;
    var own=parseColor(cs.backgroundColor);
    if(!own||own.a<0.5) continue;
    var rect=el.getBoundingClientRect();
    if(rect.width<8||rect.height<8) continue;
    if(effOpacity(el)<=0) continue;
    // 向上找最近的不透明「容器」填充色；body/html 是页面画布，不是容器，到此为止。
    var anc=null, ancSel='', ancFill='', n=el.parentElement;
    while(n && n.nodeType===1){
      if(n===document.body||n===document.documentElement) break;
      var acs=getComputedStyle(n);
      if(acs.display!=='none'&&acs.visibility!=='hidden'){
        var ac=parseColor(acs.backgroundColor);
        if(ac&&ac.a>=0.5){ anc=ac; ancSel=sel(n); ancFill=acs.backgroundColor; break; }
      }
      n=n.parentElement;
    }
    if(!anc) continue;
    if(anc.r===own.r&&anc.g===own.g&&anc.b===own.b){
      total++;
      var key=sel(el)+'|'+cs.backgroundColor+'|'+ancSel;
      if(seen[key]){
        seen[key].count++;
      }else{
        seen[key]={sel:sel(el), own:cs.backgroundColor, ownFill:cs.backgroundColor,
          ancSel:ancSel, ancFill:ancFill,
          w:Math.round(rect.width), h:Math.round(rect.height), count:1};
        out.push(seen[key]);
      }
    }
  }
  return JSON.stringify({violations:out, total:total, elements:all.length});
})()"""

# 展开 JS：把折叠态全部打开，才扫得到下拉面板 / 筛选面板 / 语言菜单。
# 不模拟鼠标，直接置 open / 加 mf-open，纯样式层面等价。
EXPAND_JS = r"""(function(){
  var n=0;
  document.querySelectorAll('details').forEach(function(d){ if(!d.open){d.open=true;n++;} });
  document.querySelectorAll('.matrix-filters').forEach(function(f){ f.classList.add('mf-open'); });
  document.querySelectorAll('.catquick.cat-hidden').forEach(function(f){ f.classList.remove('cat-hidden'); });
  document.querySelectorAll('.res-skeleton').forEach(function(f){ f.remove(); });
  return n;
})()"""

# 自动完成探针：#ac 只有输入时才 display:block，用真实 input 事件唤起，不伪造 DOM。
AC_JS = r"""(function(){
  var q=document.getElementById('q'); if(!q) return 'NO_INPUT';
  q.focus();
  q.value='at';            // 自动完成要求输入 ≥2 字（build.py「输入 ≥2 字，top 8」）
  q.dispatchEvent(new Event('input',{bubbles:true}));
  q.dispatchEvent(new Event('keyup',{bubbles:true}));
  return 'OK';
})()"""

AC_STATE_JS = r"""(function(){
  var a=document.getElementById('ac');
  if(!a) return 'NONE';
  var open=a.classList.contains('open') && a.children.length>0;
  return open?'OPEN':'CLOSED';
})()"""


# ── Chrome 探测 ─────────────────────────────────────────────────────────────
def find_chrome() -> Path | None:
    """按 注册表 → PATH → 常见安装路径 的顺序找本机 Chrome；找不到返回 None。"""
    candidates: list[Path] = []
    if os.name == "nt":
        try:
            import winreg  # noqa: PLC0415

            key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        val, _ = winreg.QueryValueEx(k, None)
                        if val:
                            candidates.append(Path(val))
                except OSError:
                    continue
        except Exception:  # noqa: BLE001 —— 没有注册表就往下走
            pass
    for name in ("chrome", "chrome.exe", "google-chrome", "chromium"):
        hit = shutil.which(name)
        if hit:
            candidates.append(Path(hit))
    candidates += [Path(p) for p in CHROME_ENV_HINTS]
    for base in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        root = os.environ.get(base)
        if root:
            candidates.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


# ── 极简 WebSocket / CDP（stdlib；与 .tmp/qa-v0101/qa_browser.py 同一套写法）──
class WS:
    def __init__(self, url: str) -> None:
        rest = url[5:]
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=30)
        self.sock.settimeout(30)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OSError("ws 握手被关闭")
            buf += chunk
        head, self.buf = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise RuntimeError(f"WS 握手失败: {head[:120]!r}")

    def _exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OSError("ws 已关闭")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _frame(self, opcode: int, data: bytes) -> bytes:
        head = bytearray([0x80 | opcode])
        n = len(data)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack("!H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack("!Q", n)
        mask = os.urandom(4)
        head += mask
        return bytes(head) + bytes(b ^ mask[i % 4] for i, b in enumerate(data))

    def send(self, text: str) -> None:
        self.sock.sendall(self._frame(0x1, text.encode()))

    def recv(self) -> str:
        parts: list[bytes] = []
        while True:
            b0, b1 = self._exact(2)
            fin, opcode = b0 & 0x80, b0 & 0x0F
            masked, n = b1 & 0x80, b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._exact(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._exact(8))[0]
            mask = self._exact(4) if masked else None
            payload = self._exact(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x9:
                self.sock.sendall(self._frame(0xA, payload))
                continue
            if opcode == 0x8:
                raise OSError("ws 收到关闭帧")
            parts.append(payload)
            if fin:
                return b"".join(parts).decode("utf-8", "replace")


class CDP:
    def __init__(self, ws_url: str) -> None:
        self.ws = WS(ws_url)
        self.seq = 0
        self.events: list[dict] = []

    def call(self, method: str, timeout: float = 60, **params):
        self.seq += 1
        mid = self.seq
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = json.loads(self.ws.recv())
            except socket.timeout:
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self.events.append(msg)
        raise TimeoutError(method)

    def drain(self, seconds: float = 0.15) -> None:
        end = time.time() + seconds
        self.ws.sock.settimeout(0.05)
        try:
            while time.time() < end:
                try:
                    self.events.append(json.loads(self.ws.recv()))
                except socket.timeout:
                    break
        finally:
            self.ws.sock.settimeout(30)

    def wait_event(self, method: str, timeout: float = 40) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            for i, ev in enumerate(self.events):
                if ev.get("method") == method:
                    self.events.pop(i)
                    return True
            self.drain(0.1)
        return False

    def eval(self, expr: str, timeout: float = 90):
        res = self.call("Runtime.evaluate", timeout=timeout, expression=expr,
                        returnByValue=True, awaitPromise=False)
        return (res.get("result") or {}).get("value")


# ── 内置静态服务（只读；根路径 = dist）──────────────────────────────────────
class Site:
    def __init__(self, root: Path, overrides: dict[str, Path] | None = None) -> None:
        self.root = root
        # 预览补丁用：rel 路径 → 替换文件（如 {"assets/style.css": .tmp/ui-surface/style-after.css}）。
        # 正式验收不要用它，直接扫构建产物。
        self.overrides = overrides or {}
        self.log: list[tuple[str, int]] = []
        self._lock = threading.Lock()

    def handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # noqa: A002
                return

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                rel = urllib.parse.unquote(parsed.path).lstrip("/")
                if rel == "" or rel.endswith("/"):
                    rel += "index.html"
                override = outer.overrides.get(rel)
                fp = override if override is not None else (outer.root / rel)
                ctype = mimetypes.guess_type(fp.name)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript",
                                                          "application/json", "application/xml"):
                    ctype += "; charset=utf-8"
                if fp.is_file() and (override is not None
                                     or fp.resolve().is_relative_to(outer.root.resolve())):
                    status, body = 200, fp.read_bytes()
                else:
                    status = 404
                    nf = outer.root / "404.html"
                    body = nf.read_bytes() if nf.is_file() else b"<h1>404</h1>"
                    ctype = "text/html; charset=utf-8"
                with outer._lock:
                    outer.log.append((self.path, status))
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def do_HEAD(self):
                self.do_GET()

        return Handler

    def start(self, port: int = 0) -> ThreadingHTTPServer:
        class QuietServer(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                return

        srv = QuietServer(("127.0.0.1", port), self.handler())
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv


# ── 浏览器驱动 ──────────────────────────────────────────────────────────────
def launch_chrome(chrome: Path, devtools_port: int, profile: Path) -> subprocess.Popen:
    profile.mkdir(parents=True, exist_ok=True)
    args = [str(chrome), "--headless=new", f"--remote-debugging-port={devtools_port}",
            f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--disable-gpu", "--disable-extensions", "--hide-scrollbars",
            "--disable-features=Translate", "--window-size=1280,900", "about:blank"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(150):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{devtools_port}/json/version",
                                        timeout=1) as r:
                json.loads(r.read())
            return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("Chrome 未就绪（--remote-debugging-port 没起来）")


def _page_ws(devtools_port: int) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{devtools_port}/json/list", timeout=5) as r:
        targets = json.loads(r.read())
    for t in targets:
        if t.get("type") == "page":
            return t["webSocketDebuggerUrl"]
    raise RuntimeError("找不到可用的 page target")


def _resolve(page: list[str], dist: Path | None, base_url: str | None) -> str | None:
    """返回可访问的相对 URL；页面都不存在时返回 None。"""
    if base_url:
        return page[0]
    assert dist is not None
    for rel in page:
        plain = rel.split("?")[0]
        if (dist / plain).is_file():
            return rel
    return None


def scan(cdp: CDP, url: str, width: int, height: int) -> dict:
    """一个页面 × 一个视口：导航 → 展开折叠 → 扫描 → 自动完成探针再扫一遍。"""
    cdp.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
             deviceScaleFactor=1, mobile=False)
    cdp.events.clear()
    cdp.call("Page.navigate", url=url)
    cdp.wait_event("Page.loadEventFired", 60)
    time.sleep(0.5)
    cdp.eval(EXPAND_JS)
    time.sleep(0.35)
    js = SCAN_JS % {"skip_tags": json.dumps(list(SKIP_TAGS)),
                    "skip_types": json.dumps(list(dict.fromkeys(SKIP_INPUT_TYPES)))}
    first = json.loads(cdp.eval(js) or "{}")
    # 自动完成下拉：只有输入才有，单独探一次
    ac = cdp.eval(AC_JS)
    extra: dict = {}
    ac_state = "NONE"
    if ac == "OK":
        time.sleep(1.2)
        try:
            ac_state = cdp.eval(AC_STATE_JS) or "NONE"
        except Exception:  # noqa: BLE001
            ac_state = "NONE"
        try:
            extra = json.loads(cdp.eval(js) or "{}")
        except Exception:  # noqa: BLE001
            extra = {}
    merged: dict[tuple[str, str, str], dict] = {}
    for part in (first, extra):
        for v in part.get("violations") or []:
            merged.setdefault((v["sel"], v["own"], v["ancSel"]), v)
    return {
        "elements": max(first.get("elements") or 0, extra.get("elements") or 0),
        "violations": list(merged.values()),
        "ac_probe": ac,
        "ac_state": ac_state,
    }


def capture(cdp: CDP, url: str, width: int, height: int, png: Path, *, expand: bool) -> None:
    """留证截图：重新导航到干净状态（清掉自动完成探针留下的输入），可选展开折叠面板。"""
    cdp.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
             deviceScaleFactor=1, mobile=False)
    cdp.events.clear()
    cdp.call("Page.navigate", url=url)
    cdp.wait_event("Page.loadEventFired", 60)
    time.sleep(0.7)
    if expand:
        cdp.eval(EXPAND_JS)
        time.sleep(0.4)
    png.parent.mkdir(parents=True, exist_ok=True)
    data = cdp.call("Page.captureScreenshot", format="png")["data"]
    png.write_bytes(base64.b64decode(data))


def run_checks(dist: Path | None, base_url: str | None, shots: Path | None,
               prefix: str, chrome: Path, allow: list[str],
               overrides: dict[str, Path] | None = None) -> dict:
    site = Site(dist, overrides) if dist is not None else None
    srv = site.start(0) if site is not None else None
    if srv is not None:
        base = f"http://127.0.0.1:{srv.server_address[1]}/"
    else:
        base = base_url or ""
    port = 9427
    # 每次跑用全新 Chrome 用户目录：否则上一轮的 localStorage（首屏 3 步引导已关闭等）
    # 会让 DOM 和这一轮不一致，前后对比就不是同一棵树了。
    profile = Path(tempfile.mkdtemp(prefix="ui-surface-chrome-"))
    out: dict = {
        "dist": str(dist) if dist else None, "base": base, "chrome": str(chrome),
        "viewports": [v[2] for v in VIEWPORTS], "pages": [], "violations": [],
        "skipped": [], "shots": [],
    }
    proc = None
    try:
        proc = launch_chrome(chrome, port, profile)
        cdp = CDP(_page_ws(port))
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        try:  # 清掉可能残留的 localStorage，保证每轮 DOM 一致
            cdp.call("Storage.clearDataForOrigin", origin=base.rstrip("/"),
                     storageTypes="local_storage")
        except Exception:  # noqa: BLE001
            pass
        for name, candidates, want_shot in PAGES:
            rel = _resolve(candidates, dist, base_url)
            if rel is None:
                out["skipped"].append({"page": name, "reason": "产物里没有该页",
                                       "tried": candidates})
                continue
            url = base + rel
            for width, height, vp in VIEWPORTS:
                res = scan(cdp, url, width, height)
                for v in res["violations"]:
                    entry = dict(v)
                    entry.update({"page": name, "viewport": vp, "url": rel})
                    out["violations"].append(entry)
                out["pages"].append({"page": name, "viewport": vp, "url": rel,
                                     "elements": res["elements"],
                                     "violations": len(res["violations"]),
                                     "ac_probe": res.get("ac_probe"),
                                     "ac_state": res.get("ac_state")})
                print(f"  [{name:8}] {vp:9} 元素 {res['elements']:5}  同色 {len(res['violations'])}")
                if shots is not None and want_shot:
                    for suffix, expand in (("", False), ("-open", True)):
                        png = shots / f"{prefix}-{name}-{width}{suffix}.png"
                        capture(cdp, url, width, height, png, expand=expand)
                        out["shots"].append(str(png.relative_to(ROOT)) if png.is_relative_to(ROOT)
                                            else str(png))
    finally:
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()
        if srv is not None:
            srv.shutdown()
        shutil.rmtree(profile, ignore_errors=True)

    allowed = [v for v in out["violations"] if _is_allowed(v, allow)]
    real = [v for v in out["violations"] if not _is_allowed(v, allow)]
    out["allowed"] = allowed
    out["violations"] = real
    out["summary"] = {
        "scans": len(out["pages"]),
        "violations": len(real),
        "allowed": len(allowed),
        "pages_with_violations": sorted({v["page"] for v in real}),
    }
    return out


def _is_allowed(v: dict, allow: list[str]) -> bool:
    for pat in allow:
        try:
            if re.search(pat, v["sel"]) or (v.get("ancSel") and re.search(pat, v["ancSel"])):
                return True
        except re.error:
            if pat in v["sel"]:
                return True
    return False


def load_allow(spec: str | None) -> list[str]:
    if not spec:
        return []
    items: list[str] = []
    path = Path(spec)
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                items.append(line)
    else:
        items += [s.strip() for s in spec.split(",") if s.strip()]
    return items


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK，中文/箭头会炸；统一按 UTF-8 输出（CI 里也一样）。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(description="同色守卫：嵌套表面填充色 == 容器填充色 即违规")
    ap.add_argument("--dist", default=str(DEFAULT_DIST), help="产物目录（默认 site/dist）")
    ap.add_argument("--base-url", default=None, help="改用已起的服务（给了就不起内置服务）")
    ap.add_argument("--json", default=None, help="结果 JSON 落盘路径")
    ap.add_argument("--allow", default=None, help="白名单：文件路径（每行一条正则）或逗号分隔")
    ap.add_argument("--shots", default=None, help="截图目录（首页/成分页 × 两视口）")
    ap.add_argument("--shot-prefix", default="ui-surface", help="截图文件名前缀")
    ap.add_argument("--override", action="append", default=[], metavar="REL=PATH",
                    help="预览补丁用：用 PATH 顶替产物里的 REL（可重复；正式验收别用）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    chrome = find_chrome()
    if chrome is None:
        print("[SKIP] 没找到本机 Chrome（试过注册表 / PATH / Program Files / LOCALAPPDATA）。")
        print("       装 Chrome 后重跑，或用 --base-url 配合已有的真浏览器环境。")
        return 0
    dist = None if args.base_url else Path(args.dist)
    if dist is not None and not dist.is_dir():
        print(f"[SKIP] 产物目录不存在：{dist}（先跑 site/build.py）")
        return 0

    started = time.time()
    print(f"== 同色守卫 == dist={dist or '(用 --base-url)'} chrome={chrome}")
    allow = load_allow(args.allow)
    if allow:
        print(f"   白名单 {len(allow)} 条：{allow}")
    shots = Path(args.shots) if args.shots else None
    overrides: dict[str, Path] = {}
    for spec in args.override:
        if "=" not in spec:
            print(f"[SKIP] --override 要写成 REL=PATH，收到 {spec!r}")
            return 0
        rel, _, p = spec.partition("=")
        overrides[rel.strip().lstrip("/")] = Path(p.strip())
    for rel, p in overrides.items():
        if not p.is_file():
            print(f"[SKIP] --override 指向的文件不存在：{rel}={p}")
            return 0
    if overrides:
        print("   ⚠ 预览模式：" + "、".join(f"{k} ← {v}" for k, v in overrides.items())
              + "（正式验收请扫构建产物，不要带 --override）")
    out = run_checks(dist, args.base_url, shots, args.shot_prefix, chrome, allow,
                     overrides or None)
    out["generated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out["elapsed_s"] = round(time.time() - started, 1)
    out["allow"] = allow
    out["overrides"] = {k: str(v) for k, v in (overrides or {}).items()}

    for sk in out["skipped"]:
        print(f"  [SKIP] {sk['page']}: {sk['reason']}（试过 {', '.join(sk['tried'])}）")

    v = out["violations"]
    print("\n== 汇总 ==")
    if v:
        for item in sorted(v, key=lambda d: (d["page"], d["viewport"], d["sel"])):
            print(f"  [FAIL] {item['page']:8} {item['viewport']:9} {item['sel'][:44]:44} "
                  f"{item['own']:20} in {item['ancSel'][:26]:26} {item['ancFill'][:20]:20} "
                  f"{item['w']}x{item['h']} x{item['count']}")
    s = out["summary"]
    print(f"{s['scans']} 次扫描（{len(PAGES)} 页 × {len(VIEWPORTS)} 视口）："
          f"同色 {s['violations']} 处（白名单放行 {s['allowed']} 处），"
          f"{out['elapsed_s']}s")
    if out["shots"]:
        print("截图：" + "、".join(out["shots"]))
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"JSON: {p}")
    return 1 if v else 0


if __name__ == "__main__":
    sys.exit(main())
