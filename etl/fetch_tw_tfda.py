"""抓台湾 TFDA「全部藥品許可證資料集」（data.gov.tw #9122）→ data/raw/tw/。

数据源
------
- 数据集页：https://data.gov.tw/dataset/9122
- 元数据 API：https://data.gov.tw/api/v2/rest/dataset/9122
- 下载入口（三个格式，ZIP 压缩）：
    https://data.fda.gov.tw/data/opendata/export/36/csv|json|xml
- 主管机关：衛生福利部食品藥物管理署（TFDA）
- 更新频率：每 7 日与「药证业务管理系统」同步（metadata updateFrequency: 7 日）
- 说明：本数据集是**西藥药品许可证**；中藥另见 DOCMAP，动物用药/化粧品不在内。
  资料量大，官方以 ZIP 提供；页面/欄位皆為繁體中文。

许可（重要）
------------
- data.gov.tw 元数据 license 代码 `1` = **政府資料開放授權條款－第1版**
  （Open Government Data License v1.0；https://data.gov.tw/license，民國104年7月27日訂定）。
- TFDA「網站資料開放宣告」（https://www.fda.gov.tw/TC/opendata.aspx）明确：
  以無償、非專屬、得再授權之方式提供；使用者得不限時間及地域重製、改作、編輯、
  公開傳輸或為其他方式利用、開發加值衍生物；**使用時應註明出處**。
- 义务：按 OGDL v1 附件「顯名聲明」格式署名（机关 + 年份 + 数据集名与版本 + 许可链接）；
  不得恶意变更资料；不授予机关背书；不及于专利/商标；个人资料自行依个资法处理。
- 本站只存事实字段（许可证号/品名/成分/剂型/规格/廠商等），不转载说明书正文。

用法
----
    python etl/fetch_tw_tfda.py                  # 元数据 + 默认 CSV ZIP 下载/缓存/解压
    python etl/fetch_tw_tfda.py --format json    # 下 JSON ZIP
    python etl/fetch_tw_tfda.py --sample 500     # 额外导出前 500 行样本 CSV
    python etl/fetch_tw_tfda.py --meta-only      # 只抓元数据
    python etl/fetch_tw_tfda.py --force          # 忽略缓存重新下载

输出（全部落在 data/raw/tw/，gitignore 不随仓库）：
    meta_9122.json        数据集元数据（含许可/更新频率/字段表/data_as_of）
    tfda_36.csv (.json)   解压后的许可证数据
    tfda_36.csv.zip       原始 ZIP（保留，便于复核）
    sample_<N>.csv        样例行（UTF-8-SIG，可直接 Excel 打开）

只读数据源；不写 data/drugs.db，不改站点。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "raw" / "tw"
DATASET_ID = 9122
META_API = f"https://data.gov.tw/api/v2/rest/dataset/{DATASET_ID}"
EXPORT = {
    "csv": "https://data.fda.gov.tw/data/opendata/export/36/csv",
    "json": "https://data.fda.gov.tw/data/opendata/export/36/json",
    "xml": "https://data.fda.gov.tw/data/opendata/export/36/xml",
}
LICENSE_URL = "https://data.gov.tw/license"
TFDA_OPEN_DATA_URL = "https://www.fda.gov.tw/TC/opendata.aspx"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
CHUNK = 1 << 20  # 1 MiB
RATE_SLEEP = 1.0  # 限速：请求之间至少 1s


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch_json(url: str, timeout: int = 60) -> dict:
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def stream_download(url: str, dest: Path, timeout: int = 300, tries: int = 3) -> dict:
    """流式下载到 .part → rename；返回 size/sha256/http 头信息。失败时保留旧缓存。"""
    for attempt in range(1, tries + 1):
        try:
            req = Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/zip,application/octet-stream,*/*",
            })
            t0 = time.time()
            part = dest.with_suffix(dest.suffix + ".part")
            h = hashlib.sha256()
            size = 0
            with urlopen(req, timeout=timeout) as r, open(part, "wb") as f:
                ctype = r.headers.get("Content-Type")
                disp = r.headers.get("Content-Disposition")
                while True:
                    chunk = r.read(CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
            part.replace(dest)
            return {"bytes": size, "sha256": h.hexdigest(), "content_type": ctype,
                    "content_disposition": disp, "seconds": round(time.time() - t0, 1),
                    "attempt": attempt}
        except (HTTPError, URLError, TimeoutError, OSError) as e:
            log(f"  ! 下载失败（第 {attempt}/{tries} 次）: {e!r}")
            if attempt < tries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"下载失败: {url}")


def save_meta(meta: dict) -> dict:
    """抽取审计需要的字段，写 meta_9122.json（含 data_as_of；保留上次的 download/local_files）。"""
    res = meta.get("result") or meta
    dist = res.get("distribution") or []
    fields = []
    for item in dist:
        rf = item.get("resourceField") or []
        if rf and not fields:
            fields = [f.get("name") for f in rf]
    freq = res.get("updateFrequency") or {}
    try:
        days = int(freq.get("Frequency") or 0)
    except (TypeError, ValueError):
        days = None
    prev: dict = {}
    meta_path = CACHE / "meta_9122.json"
    if meta_path.exists():
        try:
            prev = json.loads(meta_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            prev = {}
    out = {
        "dataset_id": DATASET_ID,
        "dataset_page": f"https://data.gov.tw/dataset/{DATASET_ID}",
        "meta_api": META_API,
        "identifier": res.get("identifier"),
        "title": res.get("title"),
        "title_en": (res.get("en") or {}).get("title"),
        "description": res.get("description"),
        "license_code": res.get("license"),
        "license_name": "政府資料開放授權條款－第1版 (OGDL v1.0)",
        "license_url": LICENSE_URL,
        "license_note": "TFDA 網站資料開放宣告：無償、非專屬、得再授權；重製/改作/編輯/公開傳輸可利用；使用時應註明出處",
        "opendata_declaration_url": TFDA_OPEN_DATA_URL,
        "publisher_oid": res.get("publisherOID"),
        "publisher_contact": {
            "name": res.get("publisherContactName"),
            "phone": res.get("publisherContactPhone"),
            "email": res.get("publisherContactEmail"),
        },
        "update_frequency": {
            "raw": freq,
            "days": days,
            "text": f"每 {days} 日" if days else str(freq),
        },
        "data_as_of": (res.get("modifiedDate") or "")[:10],
        "published_date": res.get("publishedDate"),
        "modified_date": res.get("modifiedDate"),
        "related_url": res.get("relatedUrl"),
        "notes": res.get("notes"),
        "fields": fields,
        "field_count": len(fields),
        "resources": [
            {"format": d.get("resourceFormat"),
             "url": d.get("resourceDownloadUrl"),
             "encoding": d.get("resourceCharacterEncoding"),
             "quality_check_time": d.get("resourceQualityCheckTime")}
            for d in dist
        ],
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "attribution": (
            "衛生福利部食品藥物管理署（TFDA）「全部藥品許可證資料集」；"
            "依政府資料開放授權條款第1版（https://data.gov.tw/license）釋出"
        ),
    }
    # 保留上次下载/本地文件信息（缓存命中重跑时不会丢）
    for key in ("download", "local_files"):
        if key in prev and key not in out:
            out[key] = prev[key]
    (CACHE / "meta_9122.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def record_local_files(meta: dict, paths: list[Path]) -> dict:
    """记录本地缓存文件的大小/哈希（审计可复核），并回写 meta（保留其它格式的旧记录）。"""
    local = dict(meta.get("local_files") or {})
    for p in paths:
        if not p.exists():
            continue
        b = p.read_bytes()
        local[p.name] = {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
    meta["local_files"] = local
    (CACHE / "meta_9122.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def extract_zip(zip_path: Path, fmt: str) -> Path:
    """解压出 zip 内的数据文件；返回解压后路径。"""
    target = CACHE / f"tfda_36.{fmt}"
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        pick = None
        for n in names:
            if n.lower().endswith("." + fmt):
                pick = n
                break
        if pick is None:
            # csv 导出有时成员名不是 .csv 后缀，退化为取第一个非 README 文件
            cand = [n for n in names if "readme" not in n.lower()]
            pick = cand[0] if cand else names[0]
        info = zf.getinfo(pick)
        with zf.open(pick) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return target


def read_text_rows(data_path: Path) -> tuple[list[str], list[list[str]], str]:
    """读 CSV（UTF-8/Big5 自适应），返回 header/rows/encoding。"""
    raw = data_path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "big5", "cp950"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")
        enc = "utf-8(replace)"
    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return [], [], enc
    header, body = rows[0], rows[1:]
    width = len(header)
    body = [r + [""] * (width - len(r)) if len(r) < width else r[:width] for r in body]
    return header, body, enc


def write_sample(header: list[str], body: list[list[str]], n: int,
                 prefix: str = "sample") -> Path:
    out = CACHE / f"{prefix}_{n}.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(body[:n])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="抓 TFDA 全部藥品許可證資料集 → data/raw/tw/")
    ap.add_argument("--format", choices=sorted(EXPORT), default="csv")
    ap.add_argument("--force", action="store_true", help="忽略缓存重新下载")
    ap.add_argument("--meta-only", action="store_true", help="只抓元数据")
    ap.add_argument("--sample", type=int, default=0, help="额外导出前 N 行样本 CSV")
    ap.add_argument("--timeout", type=int, default=300, help="下载超时秒数")
    args = ap.parse_args(argv)

    CACHE.mkdir(parents=True, exist_ok=True)
    log(f"== TFDA 全部藥品許可證資料集 (data.gov.tw #{DATASET_ID}) ==")

    # 1) 元数据（失败 → 有旧 meta 则降级，否则非 0）
    try:
        meta_raw = fetch_json(META_API)
        log(f"元数据 OK：modifiedDate={(meta_raw.get('result') or meta_raw).get('modifiedDate')}")
        time.sleep(RATE_SLEEP)
    except Exception as e:  # noqa: BLE001 - 元数据失败时降级使用缓存
        log(f"! 元数据获取失败: {e!r}")
        cached = CACHE / "meta_9122.json"
        if cached.exists():
            log(f"  降级：使用缓存元数据 {cached}")
            meta_raw = json.loads(json.dumps({"result": json.loads(cached.read_text('utf-8'))}))
        else:
            log("  无缓存元数据，退出")
            return 1

    meta = save_meta(meta_raw)
    log(f"  许可：{meta['license_code']} = {meta['license_name']}（{LICENSE_URL}）")
    log(f"  更新：{meta['update_frequency']['text']}；data_as_of={meta['data_as_of']}；"
        f"字段 {meta['field_count']} 个")

    if args.meta_only:
        return 0

    # 2) 下载 ZIP（已有缓存且非 --force 则跳过）
    fmt = args.format
    zip_path = CACHE / f"tfda_36.{fmt}.zip"
    if zip_path.exists() and not args.force:
        log(f"缓存命中：{zip_path}（{zip_path.stat().st_size / 1e6:.1f} MB；--force 可重下）")
    else:
        log(f"下载 {EXPORT[fmt]} …")
        info = stream_download(EXPORT[fmt], zip_path, timeout=args.timeout)
        log(f"  下载完成：{info['bytes'] / 1e6:.1f} MB，{info['seconds']}s，"
            f"sha256={info['sha256'][:16]}…")
        meta["download"] = {"format": fmt, "url": EXPORT[fmt], **info}
        (CACHE / "meta_9122.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(RATE_SLEEP)

    # 3) 解压 + 统计
    data_path = extract_zip(zip_path, fmt)
    log(f"  解压：{data_path}（{data_path.stat().st_size / 1e6:.1f} MB）")
    local_files = [zip_path, data_path]
    if fmt == "csv":
        header, body, enc = read_text_rows(data_path)
        log(f"  编码={enc} 行数={len(body):,} 列数={len(header)}")
        if args.sample > 0:
            sample = write_sample(header, body, args.sample)
            local_files.append(sample)
            log(f"  样本：{sample}（前 {min(args.sample, len(body))} 行）")
            # 另出一份「有效且未过期产品证」样本，供入库字段评审（跳过历史注销证）
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            hmap = {name: i for i, name in enumerate(header)}
            keep = []
            for r in body:
                if r[hmap.get("註銷狀態", 0)].strip():
                    continue
                kind = re.sub(r"\s+", "", r[hmap.get("許可證種類", 0)])
                if kind not in ("製劑", "菌疫"):
                    continue
                exp = r[hmap.get("有效日期", 0)].strip().replace("/", "-")
                if exp and exp < today:
                    continue
                keep.append(r)
            if keep:
                active_sample = write_sample(header, keep, min(args.sample, len(keep)),
                                             prefix="sample_active")
                local_files.append(active_sample)
                log(f"  有效证样本：{active_sample}（前 {min(args.sample, len(keep))} 行 / 共 {len(keep):,} 张有效未过期产品证）")
    else:
        log("  非 CSV 格式：跳过行数统计（可用 --format csv 获取字段覆盖）")
    record_local_files(meta, local_files)
    log("== done ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
