# -*- coding: utf-8 -*-
"""A1 产品详情数据桶生成：`data/idx/detail-<bucket>.json`（懒加载源数据；不写 DB、不改 build.py）。

依据
----
`reports/ui-a1-b6-plan.md` §2 A1：结果行点「详情」时，按索引条目的 `db` 字段
（= `_shard_bucket(key)`）懒加载一个桶；桶内 `key → 最多 12 条产品级明细`。
本脚本预先从 DB 生成这些桶；build.py 的 `db` 字段与前端接入由后续任务完成。

数据（只读 `data/drugs.db`，`mode=ro`）
---------------------------------------
- 键集合：`site/dist/data/index.json` 的 127,085 个 `k`（= `name_key.key_id`，已核对全部存在）；
- 明细行：`product_name(name_type IN ('trade','inn')) ⋈ product`，按 key 分组、每组截断；
- 行排序：status=active 优先 → country → product_id；同一 key 内按 product_id 去重；
- 行字段（12 个紧凑数组）：
  `[product_id, country, brand, pack, approval_id, status_idx, status_date,
    release_idx, strength, mah, source_url_suffix, source_idx]`
  - `brand`：该产品的第一个 trade 名（`name_variant.raw`）；
  - `strength`：成分强度串（单成分 "500 mg"；多成分 "500 mg + 125 mg"；含 per-volume 时
    "500 mg 5 ml"）；
  - `status_idx`/`release_idx`/`source_idx` 指向桶级字典 `t`/`r`/`s`；
  - `source_url` 存后缀：`url = p[source_idx] + source_url_suffix`。

体积控制（任务预算：raw ≤55 MB、gzip ≤10 MB）
--------------------------------------------
- 平铺原文字段 × cap12 ≈ 71.7 MB raw（超预算）；因此桶内做：
  1) 枚举字典：status/release/source_id 用桶级小数组下标；
  2) URL 前缀压缩：同一桶内按 source 取公共前缀，行内只存后缀；
  3) 行数上限：默认 12，若超预算自动降级 10 → 8（记录在 stats.degraded）。
- 桶文件格式（`v=1`）：
  `{"v":1,"t":[status...],"r":[release...],"s":[source_id...],"p":[url_prefix...],
    "k":{key:[[...],...]}}`
  客户端重建：`url=p[source_idx]+url_suffix`；`status=t[status_idx]`；`release=r[release_idx]`；
  `source_id=s[source_idx]`；`brand/pack/mah` 缺失为空串，前端显示「—」。

输出
----
- `data/idx/detail-<bucket>.json`（51 桶；与 build.py `_shard_bucket` 一致）；
- `.tmp/a1-detail/stats.json`：体积/行数/桶分布/编码收益/降级记录；
- `.tmp/a1-detail/sample_check.json`：抽样 key 的明细与 DB 对拍结果；
- 旧 `data/idx/detail-*.json` 先清理（只删本脚本产物）。

用法
----
    python etl/build_detail_buckets.py                 # 生成（自动按预算选行数上限）
    python etl/build_detail_buckets.py --max-rows 12   # 上限从 12 起（仍可自动降级）
    python etl/build_detail_buckets.py --no-auto-degrade
    python etl/build_detail_buckets.py --stats-only    # 只算体积，不写文件
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
INDEX = ROOT / "site" / "dist" / "data" / "index.json"
OUT_DIR = ROOT / "data" / "idx"
WORK = ROOT / ".tmp" / "a1-detail"
RAW_BUDGET = 55_000_000    # raw ≤55 MB
GZ_BUDGET = 10_000_000     # gzip ≤10 MB
DEGRADE = (12, 10, 8)
STATUSES = ["active", "discontinued", "withdrawn", "unknown"]
RELEASES = ["none", "IR", "ER", "SR", "DR", "MR", "GITS"]
ROW_FIELDS = ["product_id", "country", "brand", "pack", "approval_id", "status_idx",
              "status_date", "release_idx", "strength", "mah", "source_url_suffix",
              "source_idx"]
_BUCKET_FN = None


def load_shard_bucket():
    """优先复用 site/build.py 的 `_shard_bucket`（保证后续 `db` 字段一致），失败降级。"""
    try:
        sys.path.insert(0, str(ROOT / "site"))
        import build as site_build  # noqa: E402
        fn = site_build._shard_bucket
        assert fn("lipitor") == "l" and fn("葡萄糖注射液").startswith("cjk-")
        return fn, "site/build.py:_shard_bucket"
    except Exception as exc:  # pragma: no cover - build.py 并行修改/不可用时
        print(f"! build.py 桶函数不可用（{exc!r}），降级本地实现")
        py = {"葡": "p", "萄": "t", "糖": "t", "注": "z", "射": "s", "液": "y"}

        def fn(key: str) -> str:
            ch = (key or "")[:1]
            if not ch:
                return "other"
            if "a" <= ch <= "z":
                return ch
            if ch.isdigit():
                return "digit"
            if "\u3400" <= ch <= "\u9fff":
                return "cjk-" + py.get(ch, "x")
            return "other"

        return fn, "local fallback"


def bucket_of(key: str) -> str:
    return _BUCKET_FN(key)


# ---------------------------------------------------------------- 只读 DB 读取
def load_brands(conn: sqlite3.Connection) -> dict[str, str]:
    """product_id → 第一个 trade 名（按 raw 排序取最小，结果确定）。"""
    brands: dict[str, str] = {}
    for r in conn.execute(
        """SELECT pn.product_id, nv.raw
           FROM product_name pn JOIN name_variant nv ON nv.key_id = pn.key_id
           WHERE pn.name_type = 'trade'
           ORDER BY pn.product_id, nv.raw"""):
        brands.setdefault(r["product_id"], r["raw"] or "")
    return brands


def load_strengths(conn: sqlite3.Connection) -> dict[str, str]:
    """product_id → 强度串（多成分 ' + ' 连接；含 per-volume）。"""
    comps: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for r in conn.execute(
        """SELECT pc.product_id, pc.ord, pc.strength_value, pc.strength_unit,
                  pc.per_volume_value, pc.per_volume_unit
           FROM product_component pc ORDER BY pc.product_id, pc.ord"""):
        bits = []
        if r["strength_value"] is not None:
            sv = f"{r['strength_value']:g}"
            bits.append(f"{sv} {r['strength_unit'] or ''}".strip())
            if r["per_volume_value"] is not None:
                pv = f"{r['per_volume_value']:g}"
                bits.append(f"{pv} {r['per_volume_unit'] or ''}".strip())
        comps[r["product_id"]].append((r["ord"], " ".join(bits)))
    out: dict[str, str] = {}
    for pid, vals in comps.items():
        s = " + ".join(v for _, v in sorted(vals) if v)
        out[pid] = s
    return out


def build_rows(conn: sqlite3.Connection, keys: set[str], brands: dict[str, str],
               strengths: dict[str, str], max_rows: int
               ) -> tuple[dict[str, list[list]], list[str]]:
    """key → 明细行（截断/排序/枚举编码）+ 全局 source_id 表。"""
    rows_by_key: dict[str, list[list]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    src_idx: dict[str, int] = {}
    src_names: list[str] = []
    for r in conn.execute(
        """SELECT pn.key_id, p.product_id, p.country, p.pack, p.approval_id, p.status,
                  p.status_date, p.release, p.mah, p.source_id, p.source_url
           FROM product_name pn JOIN product p ON p.product_id = pn.product_id
           WHERE pn.name_type IN ('trade','inn')
           ORDER BY pn.key_id,
                    CASE p.status WHEN 'active' THEN 0 ELSE 1 END,
                    p.country, p.product_id"""):
        key = r["key_id"]
        if key not in keys:
            continue
        rows = rows_by_key[key]
        if len(rows) >= max_rows:
            continue
        pid = r["product_id"]
        if pid in seen[key]:
            continue
        seen[key].add(pid)
        status = (r["status"] or "unknown").strip() or "unknown"
        release = (r["release"] or "none").strip() or "none"
        sid = r["source_id"] or ""
        if sid not in src_idx:
            src_idx[sid] = len(src_names)
            src_names.append(sid)
        rows.append([
            pid,
            r["country"] or "",
            brands.get(pid, ""),
            r["pack"] or "",
            r["approval_id"] or "",
            STATUSES.index(status) if status in STATUSES else 3,
            r["status_date"] or "",
            RELEASES.index(release) if release in RELEASES else 0,
            strengths.get(pid, ""),
            r["mah"] or "",
            r["source_url"] or "",
            src_idx[sid],
        ])
    return rows_by_key, src_names


def compress_urls(rows_by_key: dict[str, list[list]], n_src: int
                  ) -> tuple[dict[str, dict[int, str]], dict]:
    """按 (bucket, source_idx) 计算 URL 公共前缀；行内 URL 改存后缀。"""
    bucket_urls: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for key, rows in rows_by_key.items():
        b = bucket_of(key)
        for row in rows:
            bucket_urls[b][row[11]].append(row[10])
    prefixes: dict[str, dict[int, str]] = {}
    saved = total = 0
    for b, per_src in bucket_urls.items():
        prefixes[b] = {}
        for sidx, urls in per_src.items():
            p = _common_prefix(urls)
            prefixes[b][sidx] = p
    for key, rows in rows_by_key.items():
        pref = prefixes[bucket_of(key)]
        for row in rows:
            url = row[10]
            total += len(url)
            p = pref.get(row[11], "")
            if p and url.startswith(p):
                row[10] = url[len(p):]
                saved += len(p)
    return prefixes, {"url_chars_total": total, "url_prefix_saved": saved}


def _common_prefix(strs: list[str]) -> str:
    if not strs:
        return ""
    lo, hi = min(strs), max(strs)
    i = 0
    for a, b in zip(lo, hi):
        if a != b:
            break
        i += 1
    return lo[:i]


def encode_buckets(rows_by_key: dict[str, list[list]], prefixes: dict[str, dict[int, str]],
                   src_names: list[str]) -> tuple[dict[str, bytes], dict]:
    """key → 桶文件 bytes；返回 {bucket: bytes} + 明细统计。"""
    per_bucket: dict[str, dict[str, list[list]]] = defaultdict(dict)
    for key, rows in rows_by_key.items():
        per_bucket[bucket_of(key)][key] = rows
    out: dict[str, bytes] = {}
    sizes = []
    for b, kmap in sorted(per_bucket.items()):
        pref_list = [""] * len(src_names)
        for sidx, p in prefixes.get(b, {}).items():
            pref_list[sidx] = p
        payload = {
            "v": 1,
            "t": STATUSES,
            "r": RELEASES,
            "s": src_names,
            "p": pref_list,
            "k": {k: kmap[k] for k in sorted(kmap)},
        }
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        out[b] = data
        sizes.append({"bucket": b, "keys": len(kmap), "rows": sum(len(v) for v in kmap.values()),
                      "raw": len(data), "gzip": len(gzip.compress(data, 9, mtime=0))})
    return out, {"buckets": sizes}


def sample_check(conn: sqlite3.Connection, rows_by_key: dict[str, list[list]],
                 prefixes: dict[str, dict[int, str]], src_names: list[str],
                 bucket_files: dict[str, bytes]) -> dict:
    """抽 3 个不同桶的 key：重建行（url/status/release/source）并与 DB 对拍。"""
    by_bucket: dict[str, str] = {}
    for key in rows_by_key:
        by_bucket.setdefault(bucket_of(key), key)
    samples = []
    for b, key in list(by_bucket.items())[:3]:
        payload = json.loads(bucket_files[b].decode("utf-8"))
        rows = payload["k"][key]
        recs = []
        ok = True
        for row in rows[:3]:
            pid, country = row[0], row[1]
            url = payload["p"][row[11]] + row[10] if row[11] < len(payload["p"]) else row[10]
            dbrow = conn.execute(
                "SELECT product_id, country, status, release, source_id, source_url "
                "FROM product WHERE product_id = ?", (pid,)).fetchone()
            match = bool(dbrow and dbrow["product_id"] == pid and dbrow["country"] == country
                         and dbrow["status"] == payload["t"][row[5]]
                         and dbrow["release"] == payload["r"][row[7]]
                         and dbrow["source_id"] == payload["s"][row[11]]
                         and dbrow["source_url"] == url)
            ok = ok and match
            recs.append({"product_id": pid, "country": country,
                         "status": payload["t"][row[5]],
                         "release": payload["r"][row[7]],
                         "source_id": payload["s"][row[11]],
                         "url_rebuilt_ok": dbrow["source_url"] == url if dbrow else False,
                         "all_fields_match": match})
        samples.append({"bucket": b, "key": key, "rows": len(rows), "sample": recs, "ok": ok})
    return {"samples": samples, "all_ok": all(s["ok"] for s in samples)}


# ---------------------------------------------------------------- 主流程
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A1 产品详情桶生成（data/idx/detail-*.json）")
    ap.add_argument("--max-rows", type=int, default=DEGRADE[0],
                    help="每 key 明细行上限（默认 12；超预算自动降级 10/8）")
    ap.add_argument("--no-auto-degrade", action="store_true", help="超预算也不降级（只报告）")
    ap.add_argument("--stats-only", action="store_true", help="只算体积，不写输出文件")
    ap.add_argument("--limit-keys", type=int, default=0, help="只取前 N 个 key（调试）")
    args = ap.parse_args(argv)

    global _BUCKET_FN
    _BUCKET_FN, bucket_src = load_shard_bucket()

    entries = json.loads(INDEX.read_text(encoding="utf-8"))
    keys = [e["k"] for e in entries]
    if args.limit_keys:
        keys = keys[: args.limit_keys]
    key_set = set(keys)
    print(f"索引条目 {len(entries):,}；参与 key {len(keys):,}；桶函数 {bucket_src}")

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    brands = load_brands(conn)
    strengths = load_strengths(conn)
    print(f"品牌映射 {len(brands):,}；强度映射 {len(strengths):,}")

    caps = [args.max_rows] if args.no_auto_degrade else [c for c in DEGRADE if c <= args.max_rows]
    if args.max_rows not in DEGRADE:
        caps = [args.max_rows] + [c for c in DEGRADE if c < args.max_rows]

    base = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "data/drugs.db (read-only) + site/dist/data/index.json k 列表",
        "protocol": "A1 detail buckets v1（reports/ui-a1-b6-plan.md §2）",
        "index_entries": len(entries), "keys": len(keys), "bucket_fn": bucket_src,
        "budgets": {"raw_bytes": RAW_BUDGET, "gzip_bytes": GZ_BUDGET},
        "row_fields": ROW_FIELDS,
        "format": "{v,t[],r[],s[],p[],k{key:[[..]]}}；url=p[source_idx]+url_suffix",
        "candidates": [],
    }

    chosen = None
    for cap in caps:
        rows_by_key, src_names = build_rows(conn, key_set, brands, strengths, cap)
        prefixes, url_stats = compress_urls(rows_by_key, len(src_names))
        files, enc = encode_buckets(rows_by_key, prefixes, src_names)
        raw = sum(len(v) for v in files.values())
        gz = sum(len(gzip.compress(v, 9, mtime=0)) for v in files.values())
        rows = sum(len(v) for v in rows_by_key.values())
        cand = {
            "max_rows": cap, "keys_out": len(rows_by_key), "rows": rows,
            "buckets": len(files), "raw_bytes": raw, "gzip_bytes": gz,
            "fits": raw <= RAW_BUDGET and gz <= GZ_BUDGET,
            "url_chars_total": url_stats["url_chars_total"],
            "url_prefix_saved": url_stats["url_prefix_saved"],
            "avg_row_bytes": round(raw / max(1, rows), 1),
        }
        base["candidates"].append(cand)
        print(f"  cap={cap}: keys={len(rows_by_key):,} rows={rows:,} buckets={len(files)} "
              f"raw={raw/1e6:.1f}MB gz={gz/1e6:.1f}MB fits={cand['fits']}")
        if chosen is None and cand["fits"]:
            chosen = (cap, rows_by_key, prefixes, src_names, files, enc, cand)
        if args.no_auto_degrade:
            chosen = (cap, rows_by_key, prefixes, src_names, files, enc, cand)
            break

    if chosen is None:
        # 全部超预算：取最小 cap 的结果并标记
        cap = caps[-1]
        rows_by_key, src_names = build_rows(conn, key_set, brands, strengths, cap)
        prefixes, url_stats = compress_urls(rows_by_key, len(src_names))
        files, enc = encode_buckets(rows_by_key, prefixes, src_names)
        raw = sum(len(v) for v in files.values())
        gz = sum(len(gzip.compress(v, 9, mtime=0)) for v in files.values())
        cand = {"max_rows": cap, "keys_out": len(rows_by_key),
                "rows": sum(len(v) for v in rows_by_key.values()), "buckets": len(files),
                "raw_bytes": raw, "gzip_bytes": gz, "fits": False,
                "url_chars_total": url_stats["url_chars_total"],
                "url_prefix_saved": url_stats["url_prefix_saved"],
                "avg_row_bytes": round(raw / max(1, sum(len(v) for v in rows_by_key.values())), 1)}
        chosen = (cap, rows_by_key, prefixes, src_names, files, enc, cand)

    cap, rows_by_key, prefixes, src_names, files, enc, cand = chosen
    stats = dict(base)
    stats.update({
        "max_rows": cap,
        "degraded": cap != args.max_rows,
        "degraded_from": args.max_rows if cap != args.max_rows else None,
        "chosen": cand,
        "buckets_written": len(files),
        "bucket_sizes": sorted(enc["buckets"], key=lambda x: -x["raw"]),
        "url_encoding": {"total_chars": cand["url_chars_total"],
                          "prefix_saved": cand["url_prefix_saved"],
                          "saved_pct": round(100 * cand["url_prefix_saved"] /
                                             max(1, cand["url_chars_total"]), 1)},
    })
    stats["sample_check"] = sample_check(conn, rows_by_key, prefixes, src_names, files)
    conn.close()

    if not args.stats_only:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        for old in OUT_DIR.glob("detail-*.json"):
            old.unlink()
        for b, data in sorted(files.items()):
            (OUT_DIR / f"detail-{b}.json").write_bytes(data)
        print(f"写文件：{len(files)} 个桶 → {OUT_DIR.relative_to(ROOT)}")
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    (WORK / "sample_check.json").write_text(
        json.dumps(stats["sample_check"], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"raw={cand['raw_bytes']/1e6:.2f}MB gz={cand['gzip_bytes']/1e6:.2f}MB "
          f"rows={cand['rows']:,} keys={cand['keys_out']:,} buckets={cand['buckets']} "
          f"cap={cap} degraded={stats['degraded']} sample_ok={stats['sample_check']['all_ok']}")
    print(f"统计：{(WORK / 'stats.json').relative_to(ROOT)}")
    return 0 if stats["sample_check"]["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
