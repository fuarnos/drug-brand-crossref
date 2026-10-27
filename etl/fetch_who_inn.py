#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WHO INN 官方列表下载器（Proposed / Recommended INN lists，WHO IRIS 与 who.int CDN）。

数据源与许可
------------
* WHO IRIS（Institutional Repository for Information Sharing）：公开检索 API 给出每条
  INN list 的 item / bitstream；PDF 头部明确写 "Proposed INN (Latin, English, French,
  Spanish)"，即官方公开电子版含 拉丁/英/法/西 四种写法（俄/中/阿版本不公开）。
* 许可：WHO 出版物按 CC BY-NC-SA 3.0 IGO 发布（IRIS item 元数据 dc.rights 可核）。
  引用要求：署名 "World Health Organization"、注明来源与许可、非商业性使用、
  相同方式共享（详见 reports/who-inn-20261026.md）。

用法
----
    python etl/fetch_who_inn.py                 # 只读缓存，打印已下载清单（不联网）
    python etl/fetch_who_inn.py --download      # 联网：发现 + 下载（缓存到 data/raw/who_inn/）
    python etl/fetch_who_inn.py --download --series both --max-files 60

产物
----
    data/raw/who_inn/meta.json   # 每个文件的 url/sha256/size/list_no/series/retrieved_at/license
    data/raw/who_inn/<series>/list_XXX.pdf
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "who_inn"
META = RAW / "meta.json"

IRIS = "https://iris.who.int/server/api"
UA = {"User-Agent": "dsh-drug-brand-crossref/0.3 (research; non-commercial; "
                    "https://fuarnos.github.io/drug-brand-crossref/)"}
LICENSE = {
    "name": "CC BY-NC-SA 3.0 IGO",
    "url": "https://creativecommons.org/licenses/by-nc-sa/3.0/igo/",
    "rights_holder": "World Health Organization",
    "note": "WHO 出版物开放获取许可；引用需署名并注明许可，禁止商业使用，衍生以相同许可共享。",
}

# IRIS 检索词：两种列表的老版（1990s–2013）标题是多语种三语对照，PDF 里
# 每个条目同时给 Latin / English / French / Spanish 名称。
DISCOVER_QUERIES = {
    "proposed": [
        "proposed international nonproprietary names list",
        "dénominations communes internationales proposées liste",
    ],
    "recommended": [
        "recommended international nonproprietary names list",
        "dénominations communes internationales recommandées liste",
    ],
}
RE_LIST_NO = re.compile(r"\blist(?:e)?\s*(\d{1,3})\b", re.IGNORECASE)
RE_TRILINGUAL = re.compile(r"(Dénominations|Denominaciones)", re.IGNORECASE)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_meta() -> dict:
    if META.exists():
        return json.loads(META.read_text(encoding="utf-8"))
    return {"created_at": now(), "license": LICENSE, "files": {}}


def save_meta(meta: dict) -> None:
    META.parent.mkdir(parents=True, exist_ok=True)
    meta["updated_at"] = now()
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def http_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def iris_search(query: str, page: int = 0, size: int = 100) -> dict:
    q = urllib.parse.quote(query)
    url = (f"{IRIS}/discover/search/objects?query={q}&dsoType=ITEM"
           f"&size={size}&page={page}")
    return http_json(url)


def discover_iris(series: str, quiet: bool = False) -> dict[int, dict]:
    """在 IRIS 中发现某系列的三语 INN list，返回 {list_no: item_info}。"""
    found: dict[int, dict] = {}
    for query in DISCOVER_QUERIES[series]:
        for page in range(0, 6):
            try:
                data = iris_search(query, page=page)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! IRIS search 失败 {query!r} page={page}: {exc}", file=sys.stderr)
                break
            objs = data.get("_embedded", {}).get("searchResult", {}) \
                       .get("_embedded", {}).get("objects", [])
            if not objs:
                break
            for obj in objs:
                ind = obj.get("_embedded", {}).get("indexableObject", {})
                name = ind.get("name") or ""
                uuid = ind.get("uuid")
                handle = ind.get("handle")
                if not uuid or not name:
                    continue
                m = RE_LIST_NO.search(name)
                if not m:
                    continue
                if not RE_TRILINGUAL.search(name):
                    continue  # 只要三语对照版（含 French/Spanish 标题）
                n = int(m.group(1))
                if series == "proposed" and not re.search(r"proposed|propos", name, re.I):
                    continue
                if series == "recommended" and not re.search(r"recommended|recommand", name, re.I):
                    continue
                found.setdefault(n, dict(series=series, list_no=n, item_uuid=uuid,
                                         handle=handle, title=name, iris_url=(
                                             f"https://iris.who.int/handle/{handle}"
                                             if handle else "")))
            if not quiet:
                print(f"  IRIS {series}: page={page} +{len(objs)} items, "
                      f"trilingual lists so far={len(found)}")
            time.sleep(0.2)
    return found


def iris_bitstreams(item_uuid: str) -> list[dict]:
    """取 ORIGINAL bundle 里的第一个 PDF bitstream。"""
    bundles = http_json(f"{IRIS}/core/items/{item_uuid}/bundles")
    for b in bundles.get("_embedded", {}).get("bundles", []):
        if b.get("name") != "ORIGINAL":
            continue
        bs = http_json(f"{IRIS}/core/bundles/{b['uuid']}/bitstreams")
        out = []
        for x in bs.get("_embedded", {}).get("bitstreams", []):
            out.append(dict(name=x["name"], size=x.get("sizeBytes"),
                            uuid=x["uuid"],
                            url=f"{IRIS}/core/bitstreams/{x['uuid']}/content"))
        return out
    return []


def fetch_iris_series(series: str, meta: dict, max_files: int) -> int:
    print(f"[{series}] 发现 IRIS 三语 INN lists ...")
    found = discover_iris(series)
    numbers = sorted(found)
    print(f"[{series}] 找到 {len(numbers)} 个三语版本: {numbers}")
    done = 0
    for n in numbers:
        if done >= max_files:
            print(f"[{series}] 达到 --max-files={max_files}，停止")
            break
        info = found[n]
        key = f"{series}/list_{n:03d}"
        if key in meta["files"] and (RAW / meta["files"][key]["path"]).exists():
            print(f"  缓存命中 {key}")
            continue
        try:
            streams = iris_bitstreams(info["item_uuid"])
            pdfs = [s for s in streams if s["name"].lower().endswith(".pdf")]
            if not pdfs:
                print(f"  ! {key} 无 PDF bitstream，跳过")
                continue
            stream = sorted(pdfs, key=lambda s: s.get("size") or 0)[0]
            data = http_bytes(stream["url"])
        except Exception as exc:  # noqa: BLE001
            print(f"  ! 下载失败 {key}: {exc}", file=sys.stderr)
            continue
        rel = f"{series}/list_{n:03d}.pdf"
        out = RAW / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        meta["files"][key] = dict(
            path=rel, series=series, list_no=n, source="WHO IRIS",
            source_url=info["iris_url"], download_url=stream["url"],
            bitstream_name=stream["name"], size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(), retrieved_at=now(),
            license=LICENSE["name"], license_url=LICENSE["url"])
        save_meta(meta)
        done += 1
        print(f"  ✓ {key} ({len(data)/1e6:.1f} MB) <- {info['iris_url']}")
    return done


def main() -> None:
    ap = argparse.ArgumentParser(description="下载 WHO INN 官方列表（默认只读缓存）。")
    ap.add_argument("--download", action="store_true", help="联网发现并下载")
    ap.add_argument("--series", choices=["proposed", "recommended", "both"],
                    default="both")
    ap.add_argument("--max-files", type=int, default=40, help="本次最多下载文件数")
    args = ap.parse_args()

    meta = load_meta()
    if not args.download:
        print(f"缓存目录: {RAW}")
        print(f"已缓存 {len(meta['files'])} 个文件")
        for k in sorted(meta["files"]):
            f = meta["files"][k]
            print(f"  {k}  {f['size_bytes']/1e6:6.1f} MB  sha256={f['sha256'][:12]}…  "
                  f"{f['source_url']}")
        print("\n(--download 才联网下载)")
        return

    series_list = ["proposed", "recommended"] if args.series == "both" else [args.series]
    total = 0
    for series in series_list:
        total += fetch_iris_series(series, meta, args.max_files - total)
        if total >= args.max_files:
            break
    save_meta(meta)
    print(f"\n本次新增 {total} 个文件；缓存共 {len(meta['files'])} 个 -> {RAW}")


if __name__ == "__main__":
    main()
