"""创建 / 更新 GitHub Release（UTF-8 安全，替代 Windows PowerShell 里的内联中文标题）。

背景：Windows PowerShell 5.1 会把「无 BOM 的 UTF-8 .ps1」按本地 ANSI 代码页读取，
内联中文字面量会变成乱码；Release 正文虽从 CHANGELOG 读取正常，标题却会坏。
统一用本脚本（Python 3，源码 UTF-8）创建 Release。

用法：
    python deploy/github_release.py --tag v0.5.1
    python deploy/github_release.py --tag v0.5.1 --name "v0.5.1 - 首搜 254KB + 西班牙复方"
    python deploy/github_release.py --tag v0.5.1 --dry-run

说明：
- token 从仓库根 `.env` 的 GITHUB_TOKEN 读取（不打印）；
- 正文默认取 CHANGELOG.md 里该版本的一节；
- Release 已存在则 PATCH 标题/正文，不存在则创建；
- 默认仓库 fuarnos/drug-brand-crossref，可用 --repo 覆盖。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "fuarnos/drug-brand-crossref"
DEFAULT_SITE = "https://fuarnos.github.io/drug-brand-crossref/"


def read_token() -> str:
    env = ROOT / ".env"
    if not env.exists():
        raise SystemExit("找不到 .env（需要 GITHUB_TOKEN）")
    text = env.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^GITHUB_TOKEN=(.+)$", text, re.M)
    if not m:
        raise SystemExit(".env 里没有 GITHUB_TOKEN")
    return m.group(1).strip()


def changelog_section(tag: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"(?ms)^## {re.escape(tag)}\b[^\n]*\n(.*?)(?=^## |\Z)", text)
    if not m:
        raise SystemExit(f"CHANGELOG.md 里没有 {tag} 一节")
    return m.group(1).strip()


def api(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "User-Agent": "drug-brand-release",
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise SystemExit(f"GitHub API {e.code}: {detail}") from e


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="创建 / 更新 GitHub Release（UTF-8 安全）")
    ap.add_argument("--tag", required=True, help="如 v0.5.1")
    ap.add_argument("--name", help="Release 标题；默认 vX - 日期")
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    body = changelog_section(args.tag) + f"\n\n---\nSite: {DEFAULT_SITE}\n"
    name = args.name or args.tag
    if args.dry_run:
        print("tag:", args.tag)
        print("name:", name)
        print("body head:", body[:120].replace("\n", " "))
        return 0

    token = read_token()
    releases = api("GET", f"https://api.github.com/repos/{args.repo}/releases?per_page=100", token)
    existing = next((r for r in releases if r["tag_name"] == args.tag), None)
    payload = {"name": name, "body": body, "draft": False, "prerelease": False}
    if existing:
        out = api("PATCH", f"https://api.github.com/repos/{args.repo}/releases/{existing['id']}", token, payload)
        print("updated:", out["html_url"])
    else:
        payload["tag_name"] = args.tag
        out = api("POST", f"https://api.github.com/repos/{args.repo}/releases", token, payload)
        print("created:", out["html_url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
