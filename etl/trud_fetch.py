"""用 TRUD API key 拉 dm+d（英国）。

用法：
    python etl/trud_fetch.py            # 列出订阅状态并下载最新一期
    python etl/trud_fetch.py --list     # 只看有什么，不下载

key 从 .env 的 TRUD_API_KEY 或同名环境变量读，不要写进代码。

TRUD 的规则：账号建好之后，还要在网页上对每个数据产品点「订阅 / Add to subscription」
并接受许可，API 才会返回该产品的 releases。f 否则 /items/{id}/releases 会返回
404 "No releases found for API key ..."。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "dmd"
BASE = "https://isd.digital.nhs.uk/trud/api/v1/keys/{key}"

# 6 = Medicines 分类；24 = dm+d，25 = dm+d supplementary（ATC/BNF 映射）
ITEMS = {24: "dm+d", 25: "dm+d supplementary"}
UA = "dmd-fetch/0.1 (research; contact: local)"


def api_key() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("TRUD_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("TRUD_API_KEY", "").strip()


def get(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_json(url: str) -> dict:
    return json.loads(get(url).decode("utf-8"))


def file_urls(key: str, item: int, release_id, fname: str) -> list[str]:
    base = f"{BASE.format(key=key)}/items/{item}/releases/{release_id}"
    # TRUD 的下载路径随版本变动过，这里按可能性依次尝试
    return [
        f"{base}/file?fileName={urllib.request.quote(fname)}",
        f"{base}/files/{urllib.request.quote(fname)}",
        f"{base}/file",
        f"{base}/download",
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--item", type=int, action="append")
    args = ap.parse_args()

    key = api_key()
    if not key:
        sys.exit("没有找到 TRUD_API_KEY（.env 或环境变量）")
    OUT.mkdir(parents=True, exist_ok=True)

    items = args.item or list(ITEMS)
    got_any = False
    for item in items:
        label = ITEMS.get(item, f"item {item}")
        url = f"{BASE.format(key=key)}/items/{item}/releases"
        try:
            meta = get_json(url)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            print(f"[{item}] {label}: HTTP {e.code} — {body}")
            print("      多半是还没在网页上订阅这个产品。")
            continue
        releases = meta.get("releases") or []
        print(f"[{item}] {label}: {len(releases)} 个可用版本")
        if not releases:
            continue
        got_any = True
        latest = releases[0]
        print(f"      最新: {latest.get('name') or latest}")
        if args.list:
            continue

        # 文件名可能的字段名不止一个
        fname = (latest.get("archiveFileName") or latest.get("fileName")
                 or latest.get("filename") or latest.get("name") or "")
        if not fname:
            print("      这个版本的元数据里没有文件名，先把原始 JSON 打出来：")
            print(json.dumps(latest, ensure_ascii=False, indent=2)[:1500])
            continue

        rid = latest.get("id") or latest.get("releaseId")
        dest = OUT / Path(fname).name
        if dest.exists() and dest.stat().st_size > 0:
            print(f"      已存在，跳过：{dest.name}")
            continue

        # 元数据里直接给了下载地址，优先用它
        candidates = []
        if latest.get("archiveFileUrl"):
            candidates.append(latest["archiveFileUrl"])
        candidates.extend(file_urls(key, item, rid, fname))

        last_err = None
        for u in candidates:
            try:
                data = get(u, timeout=600)
                dest.write_bytes(data)
                print(f"      下载完成：{dest.name}  {len(data) / 1e6:.1f} MB")
                expect = (latest.get("archiveFileSha256") or "").upper()
                if expect:
                    import hashlib
                    got = hashlib.sha256(data).hexdigest().upper()
                    print(f"      sha256 {'校验通过' if got == expect else '不匹配！'}")
                if zipfile.is_zipfile(dest):
                    with zipfile.ZipFile(dest) as zf:
                        for n in zf.namelist()[:8]:
                            print(f"        - {n}")
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
        else:
            print(f"      下载失败：{last_err}")

    if not got_any:
        print("\n结论：这个 API key 有效，但账号下还没有任何可下载的版本。")
        print("请在 TRUD 网页上对 dm+d 点「订阅 / Add to subscription」并接受许可，再重跑本脚本。")


if __name__ == "__main__":
    main()
