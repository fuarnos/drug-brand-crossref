# -*- coding: utf-8 -*-
"""Wikidata P267（ATC 码）→ substance.atc 补全（默认 dry-run）。

为什么是 Wikidata
-----------------
WHOCC 的 ATC/DDD 索引有版权，不能整表复制；Wikidata 的 P267 声明是社区整理的
结构化码值，CC0 1.0，可再发布/可改编。本站只取「码值」做跨国对齐，不复制 WHOCC
文本。缓存见 data/raw/wikidata/atc_p267.json（由 fetch_wikidata_atc.py 拉取）。

匹配策略（只补 substance.atc 为空的成分；按可靠性分路径）
--------------------------------------------------------
  1. en_exact     inn_en 归一后 = 某条英文标签（最可靠）
  2. en_base      inn_en 去掉盐/酯/水合物后缀后再匹配（如 metformin hydrochloride → metformin）
  3. zh_exact     inn_zh 归一后 = 中文标签（中文名来源 NHSA，只有几百个）
  4. mx_es_slug   substance_id = mx-es-<slug> 的拉丁/西语名 → 西语标签
                 （759 个「只在墨西哥出现」的成分，用西语名直接对 Wikidata 西语标签）
  5. es_fallback  inn_en 本身是西语写法（含 de/la/y 等词）→ 西语标签

歧义处理：同一名字命中多个 ATC 码时，若**恰好一个 7 位完整码**则采用它；否则若
**总共只有一个码**才采用；其余情况下（例如阿司匹林同时有 N02BA01/B01AC06/A01AD05）
一律跳过并计入 ambiguous，绝不猜。一个成分只写一个 ATC。

来源记录：schema 的 substance 没有来源列，所以本轮只写 atc / atc_name，并写
`source`（wikidata_atc_p267，CC0）+ `ingest_run`（统计 JSON）作为批次级出处；
逐条出处可由「缓存 + 脚本版本 + ingest_run」复现。atc_name 用 Wikidata 英文标签
（即 INN 名，接近 ATC 名称），不是 WHOCC 文本。

用法：
    python etl/ingest_wikidata_atc.py                     # 默认 dry-run，只读库
    python etl/ingest_wikidata_atc.py --dry-run --sample 30
    python etl/ingest_wikidata_atc.py --apply             # 写库（事务，幂等）
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
CACHE = ROOT / "data" / "raw" / "wikidata" / "atc_p267.json"
APPLIED = ROOT / "data" / "raw" / "wikidata" / "applied_wikidata_atc.json"
EVID = ROOT / ".tmp" / "mx-atc"
TODAY = date.today().isoformat()
SOURCE_ID = "wikidata_atc_p267"

RE_ATC = re.compile(r"^[A-Z][0-9]{2}([A-Z]{2}[0-9]{2})?$")
RE_NONALNUM = re.compile(r"[^a-z0-9]+")

# 英文 INN 的盐/酯/水合物后缀：去掉后对「母体名」，只用于唯一码回填。
EN_SALT_SUFFIX = {
    "hydrochloride", "hydrobromide", "sodium", "potassium", "calcium", "magnesium",
    "sulfate", "sulphate", "phosphate", "citrate", "maleate", "fumarate", "tartrate",
    "mesylate", "besylate", "tosylate", "acetate", "succinate", "lactate", "gluconate",
    "carbonate", "bicarbonate", "nitrate", "chloride", "bromide", "iodide",
    "hydrate", "dihydrate", "trihydrate", "monohydrate", "anhydrous", "salt",
    "hcl", "hbr", "base", "ester", "sodium salt", "potassium salt",
}
ES_FILLERS = {"de", "del", "la", "el", "los", "las", "y", "con", "para"}


def strip_acc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if not unicodedata.combining(c))


def norm(s: str) -> str:
    """拉丁名归一：去重音、小写、非字母数字→空格、压缩空格。"""
    s = strip_acc(s or "").lower()
    s = RE_NONALNUM.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_zh(s: str) -> str:
    """中文名归一：只留汉字/字母/数字。"""
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", s).lower()


def strip_en_salt(name: str) -> str:
    toks = norm(name).split()
    while toks and toks[-1] in EN_SALT_SUFFIX:
        toks.pop()
    # 末尾括号里的盐形（"metformin (hydrochloride)"）已在 norm 里变成尾巴，会被上面吃掉
    return " ".join(toks)


def looks_spanish(name: str) -> bool:
    toks = norm(name).split()
    return len(toks) >= 2 and any(t in ES_FILLERS for t in toks)


# --- 缓存 -------------------------------------------------------------------
def load_cache() -> tuple[dict, list[dict]]:
    if not CACHE.exists():
        raise SystemExit("缓存不存在：先运行 python etl/fetch_wikidata_atc.py --download")
    payload = json.loads(CACHE.read_text(encoding="utf-8"))
    return payload.get("meta") or {}, payload.get("rows") or []


def build_index(rows: list[dict]) -> tuple[dict[str, set[str]], dict[str, set[str]],
                                          dict[str, set[str]]]:
    """name → {atc} 三个索引：en / es / zh；另存 atc → 英文名。"""
    by_lang: dict[str, dict[str, set[str]]] = {"en": defaultdict(set),
                                               "es": defaultdict(set),
                                               "zh": defaultdict(set)}
    for r in rows:
        atc = (r.get("atc") or "").strip().upper()
        if not RE_ATC.match(atc):
            continue
        label = (r.get("label") or "").strip()
        lang = (r.get("lang") or "").strip().lower()
        if not label or lang not in by_lang:
            continue
        key = norm_zh(label) if lang == "zh" else norm(label)
        if key:
            by_lang[lang][key].add(atc)
    return by_lang["en"], by_lang["es"], by_lang["zh"]


def atc_names(rows: list[dict]) -> dict[str, str]:
    """ATC → 一个可读名（优先英文标签，其次西语，再次中文）。"""
    pref = {"en": 3, "es": 2, "zh": 1}
    best: dict[str, tuple[int, str]] = {}
    for r in rows:
        atc = (r.get("atc") or "").strip().upper()
        label = (r.get("label") or "").strip()
        if not atc or not label or not RE_ATC.match(atc):
            continue
        lang = (r.get("lang") or "").strip().lower()
        score = pref.get(lang, 0)
        cur = best.get(atc)
        if cur is None or score > cur[0]:
            best[atc] = (score, label)
    return {k: v[1] for k, v in best.items()}


def pick_atc(codes: set[str]) -> tuple[str | None, str]:
    """歧义处理：一个 7 位完整码 > 唯一码 > 跳过。"""
    full = {c for c in codes if len(c) == 7}
    if len(full) == 1:
        return next(iter(full)), "unique_full"
    if len(codes) == 1:
        return next(iter(codes)), "unique_only"
    return None, "ambiguous"


# --- 数据库 -----------------------------------------------------------------
def connect(db_path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = "file:" + str(db_path.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=60)
    else:
        con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def load_substances(db: sqlite3.Connection) -> tuple[list[dict], dict]:
    rows = [dict(r) for r in db.execute(
        "SELECT substance_id, inn_en, inn_zh, atc FROM substance")]
    missing = [r for r in rows if not (r["atc"] or "").strip()]
    stats = {
        "substances_total": len(rows),
        "with_atc": len(rows) - len(missing),
        "missing_atc": len(missing),
        "missing_with_inn_zh": sum(1 for r in missing if (r["inn_zh"] or "").strip()),
        "missing_mx_es": sum(1 for r in missing if r["substance_id"].startswith("mx-es-")),
    }
    return missing, stats


# --- 匹配 -------------------------------------------------------------------
def match_substances(missing: list[dict], en: dict, es: dict, zh: dict,
                     names: dict[str, str]) -> tuple[list[dict], dict, list[dict]]:
    hits: list[dict] = []
    stats: Counter = Counter()
    samples_ambiguous: list[dict] = []

    def add(hit: dict) -> None:
        hits.append(hit)

    for sub in missing:
        inn_en = (sub["inn_en"] or "").strip()
        inn_zh = (sub["inn_zh"] or "").strip()
        sid = sub["substance_id"]
        found: tuple[str, set[str], str] | None = None   # (path, codes, matched_name)

        n = norm(inn_en)
        if n and n in en:
            found = ("en_exact", en[n], inn_en)
        if found is None and n:
            base = strip_en_salt(inn_en)
            if base and base != n and base in en:
                found = ("en_base", en[base], base)
        if found is None and inn_zh:
            z = norm_zh(inn_zh)
            if z and z in zh:
                found = ("zh_exact", zh[z], inn_zh)
        if found is None and sid.startswith("mx-es-"):
            es_name = sid[len("mx-es-"):].replace("-", " ")
            ne = norm(es_name)
            if ne and ne in es:
                found = ("mx_es_slug", es[ne], es_name)
        if found is None and n and looks_spanish(inn_en):
            if n in es:
                found = ("es_fallback", es[n], inn_en)

        if found is None:
            stats["no_match"] += 1
            continue
        path, codes, matched = found
        code, how = pick_atc(codes)
        if code is None:
            stats["ambiguous"] += 1
            if len(samples_ambiguous) < 30:
                samples_ambiguous.append({"substance_id": sid, "inn_en": inn_en,
                                          "path": path, "matched": matched,
                                          "codes": sorted(codes)})
            continue
        stats[f"hit_{path}"] += 1
        hits.append({
            "substance_id": sid, "inn_en": inn_en, "inn_zh": inn_zh or None,
            "atc": code, "atc_name": names.get(code), "path": path,
            "matched_name": matched, "candidates": sorted(codes),
            "pick": how,
        })

    return hits, dict(stats), samples_ambiguous


# --- 报告 -------------------------------------------------------------------
def coverage_rows(db: sqlite3.Connection, n_fill: int) -> dict:
    row = db.execute(
        "SELECT COUNT(*) AS total,"
        " SUM(CASE WHEN atc IS NOT NULL AND atc<>'' THEN 1 ELSE 0 END) AS with_atc"
        " FROM substance").fetchone()
    total, with_atc = row["total"], row["with_atc"] or 0
    return {
        "substances_total": total,
        "with_atc_before": with_atc,
        "with_atc_after": with_atc + n_fill,
        "coverage_before": round(100.0 * with_atc / max(1, total), 1),
        "coverage_after": round(100.0 * (with_atc + n_fill) / max(1, total), 1),
    }


def write_dryrun_report(result: dict, outdir: Path) -> tuple[Path, Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    js = outdir / "wikidata_atc_dryrun.json"
    js.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines: list[str] = []
    w = lines.append
    w("# Wikidata ATC 补全 dry-run（etl/ingest_wikidata_atc.py）")
    w(f"\n生成时间：{result['generated_at']}   数据库：{result['db']}")
    w(f"缓存：{result['cache']['path']}  行 {result['cache']['rows']:,}  "
      f"药物 {result['cache']['distinct_drugs']:,}  ATC {result['cache']['distinct_atc']:,}"
      f"  许可 {result['cache']['license']}")
    s = result["match_stats"]
    g = result["gap"]
    w(f"\n## 缺口\n- 成分 {g['substances_total']:,}，有 ATC {g['with_atc']:,}，"
      f"缺 {g['missing_atc']:,}（其中 mx-es 专属 {g['missing_mx_es']:,}，"
      f"有中文名 {g['missing_with_inn_zh']:,}）")
    w("\n## 命中路径")
    for k in ("en_exact", "en_base", "zh_exact", "mx_es_slug", "es_fallback"):
        w(f"- {k}: {s.get('hit_' + k, 0):,}")
    w(f"- 歧义跳过（多码且无唯一 7 位码）: {s.get('ambiguous', 0):,}")
    w(f"- 未匹配: {s.get('no_match', 0):,}")
    c = result["coverage"]
    w(f"\n## 可补 **{result['totals']['fills']:,}** 个成分  "
      f"覆盖率 {c['coverage_before']}% → **{c['coverage_after']}%**"
      f"（{c['with_atc_before']:,} → {c['with_atc_after']:,} / {c['substances_total']:,}）")
    w("\n## 抽样 20 条")
    w("| # | substance_id | inn_en | 路径 | atc | atc_name |")
    w("|---:|---|---|---|---|---|")
    for i, h in enumerate(result["samples"], 1):
        w(f"| {i} | {h['substance_id']} | {h['inn_en']} | {h['path']} | "
          f"{h['atc']} | {h['atc_name'] or ''} |")
    w("\n## 歧义样例（不写）")
    for a in result["ambiguous"][:15]:
        w(f"- {a['substance_id']} {a['inn_en']} → {', '.join(a['codes'])}（{a['path']}）")
    txt = outdir / "wikidata_atc_dryrun.txt"
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return js, txt


# --- apply ------------------------------------------------------------------
def apply_hits(db: sqlite3.Connection, hits: list[dict], cache_meta: dict,
               match_stats: dict) -> dict:
    written = Counter()
    applied: list[dict] = []   # 本轮真正写进去的行（rollback 只认这个清单，不靠重算）
    try:
        db.execute(
            "INSERT OR REPLACE INTO source (source_id, name, url, license, license_url,"
            " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
            (SOURCE_ID, "Wikidata — ATC code (P267) statements",
             "https://www.wikidata.org/wiki/Property:P267",
             "CC0 1.0 (public domain dedication)",
             "https://creativecommons.org/publicdomain/zero/1.0/", TODAY,
             "只取 P267 码值做对齐；不复制 WHOCC 受版权保护的 ATC/DDD 文本。"))
        for h in hits:
            cur = db.execute(
                "UPDATE substance SET atc=?, atc_name=COALESCE(NULLIF(atc_name,''), ?)"
                " WHERE substance_id=? AND (atc IS NULL OR atc='')",
                (h["atc"], h["atc_name"], h["substance_id"]))
            if cur.rowcount == 1:
                written["substances"] += 1
                written[f"path_{h['path']}"] += 1
                applied.append({"substance_id": h["substance_id"], "atc": h["atc"],
                                "atc_name": h["atc_name"]})
            else:
                written["skip_race"] += 1
        note = json.dumps({"fills": len(hits), "written": dict(written),
                           "match_stats": match_stats,
                           "cache_retrieved_at": cache_meta.get("retrieved_at")},
                          ensure_ascii=False)
        db.execute(
            "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
            " rows_in, rows_kept, rows_rejected, status, note) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{SOURCE_ID}-{TODAY}", SOURCE_ID, TODAY, TODAY,
             cache_meta.get("rows", 0), written["substances"], 0, "ok", note))
        db.commit()
        APPLIED.write_text(json.dumps(
            {"applied_at": TODAY, "source_id": SOURCE_ID, "count": len(applied),
             "entries": applied}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        db.rollback()
        raise
    return dict(written)


def rollback(db: sqlite3.Connection) -> dict:
    """按 apply 时记下的清单回滚；不重算匹配，避免误伤库里原有 ATC。

    清单文件：data/raw/wikidata/applied_wikidata_atc.json（apply 时写）。
    只把「当前值仍等于清单里写入值」的成分还原为空；回滚成功后清单清空。
    """
    out = Counter()
    if not APPLIED.exists():
        raise SystemExit(
            f"找不到 {APPLIED.relative_to(ROOT)}：本 ETL 的 apply 清单不在，"
            "为免误伤库里原有 ATC，拒绝回滚。请从 data/backups/ 恢复数据库。")
    payload = json.loads(APPLIED.read_text(encoding="utf-8"))
    entries = payload.get("entries") or []
    try:
        for e in entries:
            cur = db.execute(
                "UPDATE substance SET atc=NULL,"
                " atc_name=CASE WHEN atc_name=? THEN NULL ELSE atc_name END"
                " WHERE substance_id=? AND atc=?", (e.get("atc_name"), e["substance_id"],
                                                   e["atc"]))
            if cur.rowcount == 1:
                out["substances"] += 1
        db.execute("DELETE FROM ingest_run WHERE run_id=?", (f"{SOURCE_ID}-{TODAY}",))
        db.commit()
        APPLIED.write_text(json.dumps(
            {"applied_at": payload.get("applied_at"), "source_id": SOURCE_ID,
             "count": 0, "entries": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        db.rollback()
        raise
    out["listed"] = len(entries)
    return dict(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Wikidata P267 → substance.atc（默认 dry-run）")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", action="store_true", help="撤销本 ETL 补过的 ATC（按缓存重算）")
    ap.add_argument("--sample", type=int, default=20)
    args = ap.parse_args()
    if sum([args.apply, args.dry_run, args.rollback]) > 1:
        ap.error("--apply / --dry-run / --rollback 互斥")

    cache_meta, rows = load_cache()
    en, es, zh = build_index(rows)
    names = atc_names(rows)
    db = connect(args.db, readonly=not (args.apply or args.rollback))
    missing, gap = load_substances(db)
    hits, match_stats, ambiguous = match_substances(missing, en, es, zh, names)
    if args.rollback:
        out = rollback(db)
        print(f"已回滚：{out.get('substances', 0):,} 个成分"
              f"（清单 {out.get('listed', 0):,} 条）")
        db.close()
        return 0
    cover = coverage_rows(db, len(hits))

    result = {
        "generated_at": TODAY, "db": str(args.db),
        "mode": "apply" if args.apply else "dry-run",
        "cache": {"path": str(CACHE.relative_to(ROOT)),
                  "rows": cache_meta.get("rows", len(rows)),
                  "distinct_drugs": cache_meta.get("distinct_drugs"),
                  "distinct_atc": cache_meta.get("distinct_atc"),
                  "license": cache_meta.get("license"),
                  "retrieved_at": cache_meta.get("retrieved_at")},
        "gap": gap,
        "match_stats": match_stats,
        "coverage": cover,
        "totals": {"fills": len(hits)},
        "samples": hits[: args.sample],
        "all_hits": hits,
        "ambiguous": ambiguous,
    }

    print("=== Wikidata ATC 补全 [%s] ===" % result["mode"])
    print(f"缓存：{result['cache']['rows']:,} 行 / {result['cache']['distinct_drugs']:,} 药物 / "
          f"{result['cache']['distinct_atc']:,} ATC  [{result['cache']['license']}]")
    print(f"成分 {gap['substances_total']:,}，有 ATC {gap['with_atc']:,}，"
          f"缺 {gap['missing_atc']:,}（mx-es {gap['missing_mx_es']:,}，有中文名 "
          f"{gap['missing_with_inn_zh']:,}）")
    for k, v in match_stats.items():
        print(f"  {k:<14}{v:>7,}")
    print(f"可补 {len(hits):,} 个成分；覆盖率 {cover['coverage_before']}% → "
          f"{cover['coverage_after']}%")
    print("抽样 20 条：")
    for h in hits[:20]:
        print(f"  {h['substance_id']:<34} {h['inn_en'][:32]:<34} {h['atc']:<8} "
              f"{h['atc_name'] or '':<28} [{h['path']}]")
    if ambiguous:
        print("歧义样例（跳过）：")
        for a in ambiguous[:8]:
            print(f"  {a['substance_id']:<34} {a['inn_en'][:30]:<32} {', '.join(a['codes'])}")

    if args.apply:
        written = apply_hits(db, hits, cache_meta, match_stats)
        print(f"已写库：{written.get('substances', 0):,} 个成分（事务提交）")
    else:
        js, txt = write_dryrun_report(result, EVID)
        print(f"dry-run 报告：{js.relative_to(ROOT)}  {txt.relative_to(ROOT)}")
        print("（未写 data/drugs.db；正式执行用 --apply）")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
