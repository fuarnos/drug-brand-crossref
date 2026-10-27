"""重拍「工作集群 · 架构与进度」看板。

用法（在项目根目录）：
    python render_dashboard.py                 # 重拍 HTML + PNG
    python render_dashboard.py --html-only     # 只重拍 HTML（不动 PNG）
    python render_dashboard.py --height 2200   # 指定截图高度，跳过自动测量

数据来源（全部只读）：
    data/drugs.db      产品 / 成分 / 名字键 / 碰撞 / 入库批次
    site/dist          HTML 页数、文件数、体积、索引大小
    ~/.dsh/sessions    主线会话最近活动时间（找不到就写“主线会话”）

输出：
    docs/工作集群-架构与进度.html
    docs/img/cluster-progress.png

说明：这是“按需重拍”的静态快照，不是实时监控。数字在生成那一刻定格。
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "drugs.db"
DIST = ROOT / "site" / "dist"
TEMPLATE = ROOT / "docs" / "dashboard.template.html"
OUT_HTML = ROOT / "docs" / "工作集群-架构与进度.html"
OUT_PNG = ROOT / "docs" / "img" / "cluster-progress.png"
PAGE_LIMIT = 20_000

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


# ---------------------------------------------------------------- 数据

def db_stats() -> dict[str, int]:
    out = dict(US=0, GB=0, ES=0, MX=0, CN=0, AU=0, CA=0, total=0, subst=0, keys=0, named=0,
               severe=0, warn=0, info=0, dmd_in=0, dmd_kept=0,
               gb_seed=0, gb_branded=0, es_branded=0, mx_branded=0,
               gb_trade=0, us_trade=0, cn_trade=0, au_trade=0,
               es_trade=0, mx_trade=0, atc=0)
    if not DB.exists():
        print(f"！没找到 {DB}，库里相关数字按 0 处理")
        return out

    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    try:
        def one(sql: str) -> int:
            try:
                row = con.execute(sql).fetchone()
                return int(row[0]) if row and row[0] is not None else 0
            except sqlite3.Error as exc:
                print(f"！查询失败：{sql} -> {exc}")
                return 0

        for c in ("US", "GB", "ES", "MX", "AU", "CN", "CA"):
            out[c] = one(f"select count(*) from product where country='{c}'")
        out["total"] = one("select count(*) from product")
        out["subst"] = one("select count(*) from substance")
        out["atc"] = one("select count(*) from substance where atc is not null and atc <> ''")
        out["keys"] = one("select count(*) from name_key")
        out["named"] = one("select count(*) from product_name")
        for level, key in (("severe", "severe"), ("warning", "warn"), ("info", "info")):
            out[key] = one(f"select count(*) from collision where level='{level}'")
        out["gb_seed"] = one("select count(*) from product where source_id='manual_seed' and country='GB'")
        out["gb_branded"] = one("select count(*) from product where country='GB' and is_branded=1")
        out["es_branded"] = one("select count(*) from product where country='ES' and is_branded=1")
        out["mx_branded"] = one("select count(*) from product where country='MX' and is_branded=1")
        out["gb_trade"] = one(
            "select count(distinct pn.key_id) from product_name pn "
            "join product p using(product_id) "
            "where pn.name_type='trade' and p.country='GB'")
        out["us_trade"] = one(
            "select count(distinct pn.key_id) from product_name pn "
            "join product p using(product_id) "
            "where pn.name_type='trade' and p.country='US'")
        for c in ("CN", "AU", "ES", "MX"):
            out[f"{c.lower()}_trade"] = one(
                "select count(distinct pn.key_id) from product_name pn "
                "join product p using(product_id) "
                f"where pn.name_type='trade' and p.country='{c}'")
        try:
            row = con.execute(
                "select rows_in, rows_kept from ingest_run "
                "where source_id='dmd' order by rowid desc limit 1").fetchone()
            if row:
                out["dmd_in"], out["dmd_kept"] = int(row[0] or 0), int(row[1] or 0)
        except sqlite3.Error:
            pass
    finally:
        con.close()
    return out


def dist_stats() -> dict[str, int | str]:
    out = dict(files=0, size=0, drug=0, name=0, index=0, build_time="—")
    if not DIST.exists():
        print(f"！没找到 {DIST}，站点相关数字按 0 处理")
        return out

    for p in DIST.rglob("*"):
        if p.is_file():
            out["files"] += 1
            out["size"] += p.stat().st_size
    for key, sub in (("drug", "drug"), ("name", "name")):
        d = DIST / sub
        if d.exists():
            out[key] = sum(1 for _ in d.glob("*.html"))
    idx = DIST / "data" / "index.json"
    if idx.exists():
        out["index"] = idx.stat().st_size
    entry = DIST / "index.html"
    if entry.exists():
        out["build_time"] = datetime.fromtimestamp(entry.stat().st_mtime).strftime("%H:%M")
    return out


def main_status() -> str:
    """主线会话最后一次落盘距今多久——只在本机 ~/.dsh 存在时有效。"""
    base = Path.home() / ".dsh" / "sessions"
    try:
        hits = list(base.glob("*/session-757e1865*/session.v4.jsonl.zstd"))
    except OSError:
        hits = []
    if not hits:
        return "主线会话"
    ts = max(p.stat().st_mtime for p in hits)
    dt = datetime.fromtimestamp(ts)
    mins = (time.time() - ts) / 60
    if mins < 5:
        return "运行中 · 刚刚"
    if mins < 60:
        return f"最近活动 {dt:%H:%M}"
    return f"最近活动 {dt:%m-%d %H:%M}"


# ---------------------------------------------------------------- 组装

def commas(n: int) -> str:
    return f"{n:,}"


def pct(part: int, whole: int, digits: int = 1) -> str:
    return f"{part / whole * 100:.{digits}f}" if whole else "0"


def build_tokens(db: dict, dist: dict) -> dict[str, str]:
    now = datetime.now().astimezone()
    us, gb, es, mx, au, cn, ca, total = (db["US"], db["GB"], db["ES"], db["MX"],
                                         db["AU"], db["CN"], db["CA"], db["total"])
    dmd_in, dmd_kept = db["dmd_in"], db["dmd_kept"]
    dmd_drop = max(0, dmd_in - dmd_kept)
    files = int(dist["files"])
    size_mb = int(dist["size"]) / 1e6

    keep_pct = pct(dmd_kept, dmd_in)
    drop_pct = pct(dmd_drop, dmd_in)
    keep_int = round(float(keep_pct))
    drop_int = 100 - keep_int

    deploy_note = (f"GitHub Pages（gh-pages 分支）已上线："
                   f"fuarnos.github.io/drug-brand-crossref；{commas(files)} 个文件 / {size_mb:.1f} MB。")
    p5_note = "已上线 GitHub Pages（v0.4.1）；404/robots/sitemap、懒加载索引、访问统计"

    return {
        "SNAP_TIME": f"{now:%Y-%m-%d %H:%M}",
        "SNAP_HHMM": f"{now:%H:%M}",
        "MAIN_STATUS": main_status(),
        "TOTAL": commas(total),
        "US": commas(us),
        "GB": commas(gb),
        "ES": commas(es),
        "MX": commas(mx),
        "CN": commas(cn),
        "AU": commas(au),
        "CA": commas(ca),
        "SUBST": commas(db["subst"]),
        "ATC": commas(db["atc"]),
        "KEYS": commas(db["keys"]),
        "NAMED": commas(db["named"]),
        "SEV": commas(db["severe"]),
        "WARN": commas(db["warn"]),
        "INFO": commas(db["info"]),
        "US_SHARE": pct(us, total, 0),
        "GB_SHARE": pct(gb, total, 0),
        "ES_SHARE": pct(es, total, 0),
        "MX_SHARE": pct(mx, total, 0),
        "CN_SHARE": pct(cn, total, 0),
        "AU_SHARE": pct(au, total, 0),
        "CA_SHARE": pct(ca, total, 0),
        "US_W": pct(us, total, 1),
        "GB_W": pct(gb, total, 1),
        "ES_W": pct(es, total, 1),
        "MX_W": pct(mx, total, 1),
        "CN_W": pct(cn, total, 1),
        "AU_W": pct(au, total, 1),
        "CA_W": pct(ca, total, 1),
        "CN_BAR": "100",
        "US_BAR": pct(us, cn),
        "GB_BAR": pct(gb, cn),
        "ES_BAR": pct(es, cn),
        "MX_BAR": pct(mx, cn),
        "AU_BAR": pct(au, cn),
        "CA_BAR": pct(ca, cn),
        "GB_RAW": commas(dmd_in),
        "GB_RAW_WAN": f"{dmd_in / 10000:.1f}",
        "GB_DMD": commas(dmd_kept),
        "GB_SEED": commas(db["gb_seed"]),
        "GB_KEPT": commas(dmd_kept),
        "GB_KEPT_WAN": f"{dmd_kept / 10000:.1f}",
        "GB_DROP": commas(dmd_drop),
        "GB_DROP_WAN": f"{dmd_drop / 10000:.1f}",
        "GB_KEEP_PCT": keep_pct,
        "GB_DROP_PCT": drop_pct,
        "GB_KEEP_INT": str(keep_int),
        "GB_DROP_INT": str(drop_int),
        "GB_BRANDED": commas(db["gb_branded"]),
        "ES_BRANDED": commas(db["es_branded"]),
        "MX_BRANDED": commas(db["mx_branded"]),
        "GB_TRADE": commas(db["gb_trade"]),
        "US_TRADE": commas(db["us_trade"]),
        "CN_TRADE": commas(db["cn_trade"]),
        "AU_TRADE": commas(db["au_trade"]),
        "ES_TRADE": commas(db["es_trade"]),
        "MX_TRADE": commas(db["mx_trade"]),
        "FILES": commas(files),
        "FILES_WAN": f"{files / 10000:.2f}",
        "SIZE_MB": f"{int(dist['size']) / 1e6:.1f}",
        "DRUG": commas(int(dist["drug"])),
        "NAME": commas(int(dist["name"])),
        "INDEX_MB": f"{int(dist['index']) / 1e6:.1f}",
        "BUILD_TIME": str(dist["build_time"]),
        "DEPLOY_NOTE": deploy_note,
        "P5_NOTE": p5_note,
    }


def render(tokens: dict[str, str]) -> str:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    html = re.sub(r"\{\{([A-Z0-9_]+)\}\}", lambda m: tokens.get(m.group(1), m.group(0)), tpl)
    left = sorted(set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", html)))
    if left:
        raise SystemExit(f"模板里还有没填的占位符：{', '.join(left)}")
    OUT_HTML.write_text(html, encoding="utf-8")
    return html


# ---------------------------------------------------------------- 出图

def find_browser() -> str | None:
    for c in BROWSERS:
        if Path(c).exists():
            return c
    for name in ("chrome", "msedge", "google-chrome", "chromium"):
        path = shutil.which(name)
        if path:
            return path
    return None


def shoot(html: Path, png: Path, height: int | None) -> bool:
    browser = find_browser()
    if not browser:
        print("！没找到 Chrome / Edge，PNG 未更新（HTML 已更新）")
        return False

    png.parent.mkdir(parents=True, exist_ok=True)
    profile = ROOT / ".tmp" / "chrome-profile"
    profile.mkdir(parents=True, exist_ok=True)
    base = [browser, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--disable-crash-reporter", "--disable-breakpad",
            "--hide-scrollbars", "--force-device-scale-factor=1",
            f"--user-data-dir={profile}"]

    def run(target: Path, h: int) -> bool:
        cmd = base + [f"--window-size=1500,{h}", f"--screenshot={target}", html.as_uri()]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"！浏览器启动失败：{exc}")
            return False
        if not target.exists() or target.stat().st_size == 0:
            print("！浏览器没有写出图片（沙箱下常见：命名管道被拒）")
            return False
        return True

    probe = png.parent / "_probe.png"
    if height is None:
        if not run(probe, 3000):
            return False
        measured = measure(probe)
        if measured:
            height = measured
        else:
            height = 2050
        probe.unlink(missing_ok=True)
    return run(png, height)


def measure(path: Path) -> int | None:
    try:
        from PIL import Image
        import numpy as np
    except Exception:
        return None
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).max(axis=2)
    rows = np.where((a > 90).any(axis=1))[0]
    if len(rows) == 0:
        return None
    return int(rows.max()) + 40


# ---------------------------------------------------------------- 入口

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html-only", action="store_true", help="只重拍 HTML，不动 PNG")
    ap.add_argument("--height", type=int, default=None, help="固定截图高度（默认自动测量）")
    args = ap.parse_args()

    if not TEMPLATE.exists():
        raise SystemExit(f"缺少模板：{TEMPLATE}")

    db = db_stats()
    dist = dist_stats()
    if int(dist["files"]) < 1000:
        print("！dist 文件数异常少，站点可能正在重建；这次快照的数字不可信")
    tokens = build_tokens(db, dist)
    render(tokens)

    print(f"HTML  {OUT_HTML}  ({OUT_HTML.stat().st_size / 1024:.1f} KB)")
    print(f"数字  US {tokens['US']} · GB {tokens['GB']} · CN {tokens['CN']} "
          f"· 产品 {tokens['TOTAL']} · 文件 {tokens['FILES']} · 索引 {tokens['INDEX_MB']} MB")

    if args.html_only:
        return
    if shoot(OUT_HTML, OUT_PNG, args.height):
        print(f"PNG   {OUT_PNG}  ({OUT_PNG.stat().st_size / 1024:.0f} KB)")
    else:
        raise SystemExit("PNG 没生成；HTML 已更新，可先打开 HTML 看。")


if __name__ == "__main__":
    main()
