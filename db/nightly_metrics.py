#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""夜间数据质量指标（只读）：DB + site/dist → reports/metrics/YYYY-MM-DD.json。

每晚跑一次，把「数据覆盖 / 碰撞 / 重复成分 / 站点体积」写成一份快照，并与上一份
快照对比；回退超过阈值时输出 warnings（早报据此标红）。**绝不写库、不建站、不改站点。**

用法（在仓库根跑）：
    & $py db/nightly_metrics.py                       # 写 reports/metrics/<今天>.json
    & $py db/nightly_metrics.py --date 2026-10-27     # 指定日期（补跑/覆盖当天）
    & $py db/nightly_metrics.py --fail-on-warning     # 有 warning 时退出码 1（接 cron 用）
    & $py db/nightly_metrics.py --print-json          # 额外把 JSON 打到 stdout

退出码：0 = 指标已写（允许 warnings）；1 = 读取 DB/dist 失败或 --fail-on-warning 且有 warning；2 = 参数错误。

指标口径（详见 reports/release-guardrails.md）：
  countries.<CC>.products / active_products / products_with_strength / strength_pct
  totals.products / components / substances / variants / name_keys / names / aliases ...
  atc.substances / with_atc / coverage_pct
  collisions.info / warning / severe
  duplicates.pairs / ids（判据同 etl/auto_merge_substances.py：同 ATC 前 5 位 +
    inn_en 归一化后相同或 inn_zh 相同）
  pages.total_files / html_total / drug_pages / name_pages / total_bytes
  sizes.first_screen_gz / first_search_gz / core_gz / index_gz / raw 体积
  sitemap.urls
阈值（改动需同步报告）：
  产品数/成分数/页面数/sitemap 数 下降 > 1%；规格覆盖率/ATC 覆盖率 下降 > 1pp；
  severe 碰撞数 变化 > 5%（暴增也是数据异常信号）；重复成分对数 增加 > 20%；
  首搜体积（gzip）增加 > 5%；首屏体积（gzip）增加 > 10%。
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import date, datetime
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "drugs.db"
DIST = ROOT / "site" / "dist"
OUT_DIR = ROOT / "reports" / "metrics"
SCHEMA = 1

# (指标模式, 方向, 阈值, 说明) —— 见文件头注释
RULES: list[tuple[str, str, float, str]] = [
    ("totals.products", "drop_pct", 1.0, "产品总数下降"),
    ("totals.components", "drop_pct", 1.0, "产品成分行下降"),
    ("totals.substances", "drop_pct", 1.0, "成分数下降"),
    ("totals.name_keys", "drop_pct", 1.0, "名字键数下降"),
    ("totals.names", "drop_pct", 1.0, "产品名行下降"),
    ("atc.coverage_pct", "drop_pp", 1.0, "ATC 覆盖率下降"),
    ("collisions.severe", "change_pct", 5.0, "severe 碰撞数变化"),
    ("collisions.warning", "change_pct", 5.0, "warning 碰撞数变化"),
    ("duplicates.pairs", "rise_pct", 20.0, "重复成分对数增加"),
    ("pages.total_files", "drop_pct", 1.0, "站点文件数下降"),
    ("pages.html_total", "drop_pct", 1.0, "HTML 页面数下降"),
    ("pages.drug_pages", "drop_pct", 1.0, "成分页数下降"),
    ("pages.name_pages", "drop_pct", 1.0, "名字页数下降"),
    ("sitemap.urls", "drop_pct", 1.0, "sitemap URL 数下降"),
    ("sizes.first_search_gz", "rise_pct", 5.0, "首搜体积（gzip）增加"),
    ("sizes.first_screen_gz", "rise_pct", 10.0, "首屏体积（gzip）增加"),
    ("sizes.core_gz", "rise_pct", 5.0, "索引核心 core.json 体积增加"),
    ("pages.sitemap_urls", "drop_pct", 1.0, "sitemap URL 数下降"),
    ("countries.*.products", "drop_pct", 1.0, "某国产品数下降"),
    ("countries.*.strength_pct", "drop_pp", 1.0, "某国规格覆盖率下降"),
]


# ── 只读 DB ──────────────────────────────────────────────────────────
def connect_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def has_obj(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        (name,)).fetchone() is not None


def scalar(con: sqlite3.Connection, sql: str, default=0):
    row = con.execute(sql).fetchone()
    return row[0] if row is not None and row[0] is not None else default


def norm_name(s: str) -> str:
    """同 etl/auto_merge_substances.py：NFKD 小写后只留字母数字 + 汉字。"""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", s)


def db_metrics(con: sqlite3.Connection) -> dict:
    counts: dict[str, int] = {}
    for label, sql in (
        ("products", "SELECT COUNT(*) FROM product"),
        ("components", "SELECT COUNT(*) FROM product_component"),
        ("substances", "SELECT COUNT(*) FROM substance"),
        ("variants", "SELECT COUNT(*) FROM variant"),
        ("name_keys", "SELECT COUNT(*) FROM name_key"),
        ("names", "SELECT COUNT(*) FROM product_name"),
        ("aliases", "SELECT COUNT(*) FROM alias_all"),
        ("nicknames", "SELECT COUNT(*) FROM nickname"),
        ("drug_terms", "SELECT COUNT(*) FROM drug_term"),
        ("confusable_pairs", "SELECT COUNT(*) FROM confusable_pair"),
        ("artg_entries", "SELECT COUNT(*) FROM artg_entry" if has_obj(con, "artg_entry") else
         "SELECT 0"),
        ("dose_warnings_published",
         "SELECT COUNT(*) FROM dose_warning WHERE status = 'published'"
         if has_obj(con, "dose_warning") else "SELECT 0"),
    ):
        counts[label] = int(scalar(con, sql))

    countries: dict[str, dict] = {}
    for r in con.execute(
        """SELECT p.country,
                  COUNT(DISTINCT p.product_id) AS products,
                  COUNT(DISTINCT CASE WHEN p.status = 'active'
                                      THEN p.product_id END) AS active_products,
                  COUNT(DISTINCT CASE WHEN pc.strength_value IS NOT NULL
                                      THEN p.product_id END) AS products_with_strength,
                  COUNT(DISTINCT pc.variant_id) AS variants
           FROM product p
           LEFT JOIN product_component pc ON pc.product_id = p.product_id
           GROUP BY p.country ORDER BY p.country"""):
        n = int(r["products"] or 0)
        ws = int(r["products_with_strength"] or 0)
        countries[r["country"]] = {
            "products": n,
            "active_products": int(r["active_products"] or 0),
            "products_with_strength": ws,
            "strength_pct": round(100.0 * ws / n, 2) if n else 0.0,
            "variants": int(r["variants"] or 0),
        }

    sub_total = counts["substances"]
    with_atc = int(scalar(
        con, "SELECT COUNT(*) FROM substance WHERE atc IS NOT NULL AND atc <> ''"))
    atc = {"substances": sub_total, "with_atc": with_atc,
           "coverage_pct": round(100.0 * with_atc / sub_total, 2) if sub_total else 0.0}

    collisions = {"info": 0, "warning": 0, "severe": 0}
    for r in con.execute("SELECT level, COUNT(*) AS n FROM collision GROUP BY level"):
        collisions[r["level"]] = int(r["n"])
    collisions["total"] = sum(collisions[k] for k in ("info", "warning", "severe"))

    alias_conf: dict[str, int] = {}
    for r in con.execute(
            "SELECT confidence, COUNT(*) AS n FROM alias_all GROUP BY confidence"):
        alias_conf[r["confidence"]] = int(r["n"])

    duplicates = duplicate_substances(con)
    ingest = {
        "running": int(scalar(con, "SELECT COUNT(*) FROM ingest_run WHERE status = 'running'")),
        "failed": int(scalar(con, "SELECT COUNT(*) FROM ingest_run WHERE status = 'failed'")),
    }
    return {"totals": counts, "countries": countries, "atc": atc,
            "collisions": collisions, "alias_confidence": alias_conf,
            "duplicates": duplicates, "ingest": ingest}


def duplicate_substances(con: sqlite3.Connection) -> dict:
    """同「同一成分被拆成两个 id」的疑似重复（只读复刻 auto_merge 判据，不写库）。"""
    rows = con.execute(
        "SELECT substance_id, inn_en, inn_zh, atc FROM substance").fetchall()
    by_atc: dict[str, list[tuple[str, str, str]]] = {}
    for r in rows:
        atc = r["atc"] or ""
        if len(atc) >= 5:
            by_atc.setdefault(atc[:5], []).append(
                (r["substance_id"], r["inn_en"] or "", r["inn_zh"] or ""))
    pairs = 0
    ids: set[str] = set()
    groups = 0
    for group in by_atc.values():
        if len(group) < 2:
            continue
        group_pairs = 0
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                na, nb = norm_name(a[1]), norm_name(b[1])
                if not na or not nb:
                    continue
                if na == nb or (a[2] and a[2] == b[2]):
                    pairs += 1
                    group_pairs += 1
                    ids.update((a[0], b[0]))
        groups += 1 if group_pairs else 0
    return {"pairs": pairs, "ids": len(ids), "atc4_groups": groups,
            "definition": "同 ATC 前 5 位 + inn_en 归一化相同或 inn_zh 相同"
                          "（同 etl/auto_merge_substances.py）"}


# ── site/dist ────────────────────────────────────────────────────────
def file_sizes(p: Path) -> dict:
    data = p.read_bytes()
    return {"raw": len(data), "gz": len(gzip.compress(data, 9, mtime=0))}


def dist_metrics(dist: Path) -> tuple[dict, dict]:
    if not dist.is_dir():
        raise FileNotFoundError(f"site/dist 不存在（先跑 site/build.py）: {dist}")
    files = [p for p in dist.rglob("*") if p.is_file()]
    html = [p for p in files if p.suffix.lower() == ".html"]
    drug_dir, name_dir = dist / "drug", dist / "name"
    pages = {
        "total_files": len(files),
        "html_total": len(html),
        "drug_pages": len([p for p in drug_dir.glob("*.html")]) if drug_dir.is_dir() else 0,
        "name_pages": len([p for p in name_dir.glob("*.html")]) if name_dir.is_dir() else 0,
        "total_bytes": sum(p.stat().st_size for p in files),
    }
    sitemap_urls = 0
    sm = dist / "sitemap.xml"
    if sm.is_file():
        sitemap_urls = sm.read_text(encoding="utf-8").count("<url>")
    pages["sitemap_urls"] = sitemap_urls

    paths = {
        "index_html": dist / "index.html",
        "app_js": dist / "assets" / "app.js",
        "i18n_js": dist / "assets" / "i18n.js",
        "style_css": dist / "assets" / "style.css",
        "core": dist / "data" / "idx" / "core.json",
        "index": dist / "data" / "index.json",
        "aliases": dist / "data" / "aliases.json",
        "confused": dist / "data" / "confused.json",
        "manifest": dist / "data" / "idx" / "manifest.json",
    }
    sizes: dict = {}
    for key, p in paths.items():
        if p.is_file():
            sizes[key] = file_sizes(p)
        else:
            sizes[key] = {"raw": 0, "gz": 0, "missing": True}
    first_screen = sum(sizes[k]["gz"] for k in
                       ("index_html", "app_js", "i18n_js", "style_css"))
    shard_files = sorted((dist / "data" / "idx").glob("shard-*.json"))
    shard_gzs = sorted(file_sizes(p)["gz"] for p in shard_files) if shard_files else []
    shard_median = shard_gzs[len(shard_gzs) // 2] if shard_gzs else 0
    if shard_files and sizes["manifest"]["gz"]:
        # P2 分片：首搜 = manifest + 1 个分片 + 别名/碰撞索引（core 后台兜底）
        first_search = sizes["manifest"]["gz"] + shard_median + sizes["aliases"]["gz"] + sizes["confused"]["gz"]
    else:
        first_search = sum(sizes[k]["gz"] for k in ("core", "aliases", "confused"))
    sizes["first_screen_gz"] = first_screen
    sizes["first_search_gz"] = first_search
    sizes["manifest_gz"] = sizes["manifest"]["gz"]
    sizes["shard_median_gz"] = shard_median
    sizes["shard_count"] = len(shard_files)
    sizes["core_gz"] = sizes["core"]["gz"]
    sizes["index_gz"] = sizes["index"]["gz"]
    sizes["core_raw"] = sizes["core"]["raw"]
    sizes["index_raw"] = sizes["index"]["raw"]
    del sizes["manifest"]
    del sizes["core"]
    del sizes["index"]
    dist_meta = {
        "files": len(files),
        "newest_mtime": max(p.stat().st_mtime for p in files),
    }
    return {"pages": pages, "sizes": sizes}, dist_meta


# ── 对比 / 阈值 ──────────────────────────────────────────────────────
def flatten(d: dict, prefix: str = "") -> dict:
    out: dict = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(flatten(v, key))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = float(v) if isinstance(v, float) else int(v)
    return out


def rel_path(p: Path | None) -> str | None:
    """展示用路径：仓库内的写相对路径，仓库外写绝对路径。"""
    if p is None:
        return None
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def prev_metrics_file(out_dir: Path, target: date) -> Path | None:
    if not out_dir.is_dir():
        return None
    cands = []
    for p in out_dir.glob("*.json"):
        try:
            d = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if d < target:
            cands.append((d, p))
    return sorted(cands)[-1][1] if cands else None


def compare(prev: dict, cur: dict) -> tuple[dict, list]:
    flat_prev, flat_cur = flatten(prev), flatten(cur)
    deltas: dict = {}
    for key, cv in flat_cur.items():
        if key not in flat_prev:
            continue
        pv = flat_prev[key]
        delta = cv - pv
        pct = (delta / abs(pv) * 100.0) if pv else None
        deltas[key] = {"prev": pv, "cur": cv, "delta": round(delta, 4),
                       "pct": round(pct, 2) if pct is not None else None}
    warnings: list[dict] = []
    for pattern, kind, threshold, label in RULES:
        for key, d in deltas.items():
            if not fnmatch(key, pattern):
                continue
            pv, cv = d["prev"], d["cur"]
            hit = False
            amount = 0.0
            if kind == "drop_pct" and pv:
                amount = -d["pct"] if d["pct"] is not None else 0.0
                hit = amount > threshold
            elif kind == "rise_pct" and pv:
                amount = d["pct"] if d["pct"] is not None else 0.0
                hit = amount > threshold
            elif kind == "drop_pp":
                amount = pv - cv
                hit = amount > threshold
            elif kind == "rise_abs":
                amount = cv - pv
                hit = amount > threshold
            elif kind == "change_pct" and pv:
                amount = abs(d["pct"]) if d["pct"] is not None else 0.0
                hit = amount > threshold
            if hit:
                warnings.append({
                    "metric": key, "label": label, "kind": kind,
                    "threshold": threshold, "prev": pv, "cur": cv,
                    "delta": d["delta"], "pct": d["pct"],
                    "message": f"{label}: {pv} → {cv}（{d['pct']:+.2f}%，阈值 {threshold}{'pp' if kind == 'drop_pp' else '%'}）",
                })
    return deltas, warnings


# ── main ─────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="夜间数据质量指标（只读）")
    ap.add_argument("--date", default="", help="指标日期 YYYY-MM-DD（默认今天）")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--dist", default=str(DIST))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--print-json", action="store_true", help="把 JSON 也打印到 stdout")
    ap.add_argument("--fail-on-warning", action="store_true")
    args = ap.parse_args()

    try:
        target = date.fromisoformat(args.date) if args.date else date.today()
    except ValueError:
        print("FATAL: --date 需要 YYYY-MM-DD", file=sys.stderr)
        return 2
    db_path, dist = Path(args.db), Path(args.dist)
    out_dir = Path(args.out_dir)
    if not db_path.is_file():
        print(f"FATAL: DB 不存在: {db_path}", file=sys.stderr)
        return 1
    t0 = time.perf_counter()

    try:
        con = connect_ro(db_path)
        metrics = db_metrics(con)
        con.close()
        dist_data, dist_meta = dist_metrics(dist)
    except Exception as e:
        print(f"FATAL: 读取失败: {e}", file=sys.stderr)
        return 1
    metrics.update(dist_data)

    out_dir.mkdir(parents=True, exist_ok=True)
    # 现场状态告警（与上一份对比无关）：dist 正在构建 / 关键文件缺失
    pre_warnings: list[dict] = []
    age = time.time() - dist_meta["newest_mtime"]
    if age < 120:
        pre_warnings.append({
            "metric": "dist.newest_mtime", "label": "site/dist 刚被写入",
            "message": f"site/dist 最新文件仅 {age:.0f}s 前写入，可能正在构建（本次指标仅供参考）"})
    for key, label in (("core_gz", "data/idx/core.json"), ("index_gz", "data/index.json")):
        if not metrics["sizes"].get(key):
            pre_warnings.append({
                "metric": f"sizes.{key}", "label": f"{label} 缺失",
                "message": f"{label} 缺失或为 0 字节（站点构建不完整？）"})
    if metrics["ingest"]["running"]:
        pre_warnings.append({
            "metric": "ingest.running", "label": "有入库任务在跑",
            "message": f"{metrics['ingest']['running']} 条 ingest_run 状态为 running"
                       "（本次指标是并发写入中的快照，或上次入库未正常结束）"})
    prev_path = prev_metrics_file(out_dir, target)
    prev_payload = None
    if prev_path:
        try:
            prev_payload = json.loads(prev_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"warn: 上一份指标读取失败 {prev_path}: {e}", file=sys.stderr)
    deltas, warnings = ({}, []) if not prev_payload else compare(
        prev_payload.get("metrics", {}), metrics)
    if prev_payload is None:
        warnings = [{"metric": None, "label": "无上一份指标",
                     "message": f"未找到 {target} 之前的指标文件；本次为基线快照"}]
    warnings = pre_warnings + warnings

    payload = {
        "schema": SCHEMA,
        "date": target.isoformat(),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "sources": {
            "db": {"path": rel_path(db_path),
                   "bytes": db_path.stat().st_size,
                   "mtime": datetime.fromtimestamp(db_path.stat().st_mtime).isoformat(timespec="seconds")},
            "dist": {"path": rel_path(dist),
                     "files": dist_meta["files"],
                     "newest_mtime": datetime.fromtimestamp(dist_meta["newest_mtime"]).isoformat(timespec="seconds")},
        },
        "metrics": metrics,
        "compare": {
            "prev_file": rel_path(prev_path),
            "prev_date": prev_payload.get("date") if prev_payload else None,
            "deltas": deltas,
        },
        "warnings": warnings,
        "ok": True,
    }
    out_path = out_dir / f"{target.isoformat()}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")

    m = metrics
    print(f"== 夜间指标 {target}（{payload['elapsed_s']}s）==")
    print(f"  产品 {m['totals']['products']:,} | 成分 {m['totals']['substances']:,} | "
          f"ATC {m['atc']['coverage_pct']}% | severe {m['collisions']['severe']:,} | "
          f"重复成分 {m['duplicates']['pairs']} 对")
    print(f"  页面 {m['pages']['html_total']:,} HTML / {m['pages']['total_files']:,} 文件 | "
          f"sitemap {m['pages']['sitemap_urls']:,} | 首搜 {m['sizes']['first_search_gz'] / 1e6:.2f} MB gz | "
          f"首屏 {m['sizes']['first_screen_gz']:,} B gz")
    print(f"  上一份: {prev_path.name if prev_path else '（无，本次为基线）'}")
    if warnings:
        print(f"\n  WARNINGS（{len(warnings)}）:")
        for w in warnings:
            print(f"   - {w.get('message', w)}")
    print(f"\n写入: {out_path}")
    if args.print_json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    return 1 if (args.fail_on_warning and warnings and prev_payload is not None) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
