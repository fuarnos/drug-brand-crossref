#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""数据库优化审计 + 索引建议（默认只读 dry-run；apply/rollback **仅在副本**上执行）。

用法（仓库根）：
    & $py db/optimize_indexes.py                     # dry-run：PRAGMA/FK/integrity、EXPLAIN、VACUUM 评估、
                                                     #          重复成分 & 同盐 variant 审计（只读真实库）
    & $py db/optimize_indexes.py --full-integrity    # integrity_check（慢，默认 quick_check）
    & $py db/optimize_indexes.py --apply             # 复制 data/drugs.db → .tmp/db-opt/work.db，
                                                     #          建建议索引 + 可选 VACUUM，跑前后基准，写 manifest
    & $py db/optimize_indexes.py --apply --vacuum    # 副本上同时 VACUUM（当前实测 -127.6 MB / -28.3%）
    & $py db/optimize_indexes.py --rollback          # 按 manifest 删掉 create 的索引并校验副本
    & $py db/optimize_indexes.py --apply --include-optional   # 连「可选」索引一起建

安全红线：
  * **真实库 data/drugs.db 永远只读**：dry-run 用 mode=ro；apply/rollback 只操作
    .tmp/db-opt/work.db（或 --copy 指定的副本），路径等于真实库时直接拒绝。
  * 不建 ANALYZE 统计：实测全库 ANALYZE 会让 site/build.py 的 load_index 查询
    2.99 s→7.29 s（+144%）、drug 产品查询 1.13 s→3.97 s（+252%）。详见报告 §3。
  * 不删/不改任何数据行（重复成分与同盐 variant 只出「可合并清单」，合并是另一个任务）。

退出码：0 = 正常（dry-run 完成 / apply / rollback 成功）；1 = 失败；2 = 参数错误。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "drugs.db"
TMP = ROOT / ".tmp" / "db-opt"
COPY = TMP / "work.db"
MANIFEST = TMP / "applied.json"

# ── 索引建议（依据 .tmp/db-opt/bench2.json 实测）───────────────────────
# 说明：本库瓶颈是 40–57 万行的大表全表聚合（build 的 load_index / collision 视图），
# 不是缺索引；下面只列**实测有正收益且无副作用**的小索引。实测被否掉的方案见 REJECTED。
RECOMMENDED = [
    {
        "name": "idx_artg_name",
        "sql": "CREATE INDEX IF NOT EXISTS idx_artg_name ON artg_entry (name)",
        "why": "site/build.py ARTG 列表 SELECT ... FROM artg_entry ORDER BY name："
               "50.0 ms → 30.6 ms（-39%，免 temp b-tree 排序）",
        "estimated_bytes": 1_500_000,
        "risk": "低（34,594 行小表；只增建索引成本 ~0.04 s）",
    },
    {
        "name": "idx_variant_substance",
        "sql": "CREATE INDEX IF NOT EXISTS idx_variant_substance ON variant (substance_id)",
        "why": "lib/search.py / 成分页 `SELECT * FROM variant WHERE substance_id=?`："
               "SCAN variant 0.6 ms → 0.1 ms",
        "estimated_bytes": 300_000,
        "risk": "低（13,886 行小表）",
    },
]
OPTIONAL = [
    {
        "name": "idx_name_variant_kvr",
        "sql": "CREATE INDEX IF NOT EXISTS idx_name_variant_kvr"
               " ON name_variant (key_id, v_id, raw)",
        "why": "site/build.py load_index 的 `SELECT key_id, raw FROM name_variant"
               " ORDER BY key_id, v_id`：131.4 ms → 68.1 ms（-48%；覆盖索引，免 temp b-tree）",
        "estimated_bytes": 10_100_000,
        "risk": "低但收益小（每次构建省 ~63 ms，索引 ~10 MB）；故列为可选",
    },
]
# 实测被否掉的候选（写进报告，避免后人重复踩坑）
REJECTED = [
    {"name": "ANALYZE（全库）",
     "why": "统计信息让 load_index 3.0→7.3 s（+144%）、drug 产品查询 1.1→4.0 s（+252%）："
            "规划器改用「SCAN variant + 索引回查 product_component」的坏计划。**不要跑 ANALYZE。**"},
    {"name": "idx_product_name_cover (name_type, key_id, product_id)",
     "why": "drug_names 655→182 ms（-72%）但 load_index 2.99→8.75 s（+193%）、"
            "check_data top trade US 478→1,157 ms（+142%）：整体得不偿失，不建。"},
    {"name": "idx_name_variant_key_vid (key_id, v_id)（不含 raw）",
     "why": "非覆盖索引：displays 查询 131→443 ms（+237%，走索引后逐行回表取 raw）。"
            "要建就建 (key_id, v_id, raw) 覆盖索引（即 OPTIONAL）。"},
    {"name": "idx_product_source (source_id)",
     "why": "基准查询无变化（load_index 2,990→2,991 ms）；现有 SQL 没有按 source 过滤的慢查询。"},
]

# ── 基准查询（与 site/build.py、lib/search.py、db/check_data.py 对应）──
BENCH = {
    "load_index_displays": "SELECT key_id, raw FROM name_variant ORDER BY key_id, v_id",
    "load_index_main": """
        SELECT pn.key_id, p.product_id, p.country, p.form_base, p.dosage_form,
               pc.strength_value, pc.strength_unit, s.inn_en, s.substance_id, p.mah,
               pn.name_type,
               (SELECT COUNT(*) FROM product_component pc2
                WHERE pc2.product_id = p.product_id) AS n_ing
        FROM product_name pn
        JOIN product p ON p.product_id = pn.product_id
        JOIN product_component pc ON pc.product_id = p.product_id
        JOIN variant v ON v.variant_id = pc.variant_id
        JOIN substance s ON s.substance_id = v.substance_id
        WHERE pn.name_type IN ('trade', 'inn')""",
    "drug_names_trade": """
        SELECT pn.product_id, nv.raw FROM product_name pn
        JOIN name_variant nv ON nv.key_id = pn.key_id
        WHERE pn.name_type = 'trade'""",
    "top_trade_us": """
        SELECT nv.raw, COUNT(DISTINCT pn.product_id) c
        FROM product_name pn
        JOIN name_variant nv ON nv.key_id = pn.key_id
        JOIN product p ON p.product_id = pn.product_id
        WHERE pn.name_type = 'trade' AND p.country = 'US'
        GROUP BY nv.raw ORDER BY c DESC LIMIT 12""",
    "artg_list": "SELECT name_norm, name, sponsor, artg_id FROM artg_entry ORDER BY name",
    "variant_by_sid": "SELECT * FROM variant WHERE substance_id = 'atorvastatin'",
}
# apply 前后对比用的子集（load_index_main 很重，重复 1 次；其余 2 次取最好）
BENCH_APPLY = ["load_index_displays", "load_index_main", "drug_names_trade",
               "top_trade_us", "artg_list", "variant_by_sid"]
BIG_TABLES = ("product", "product_component", "product_name", "name_variant",
              "name_key", "variant", "substance")


# ── 通用工具 ──────────────────────────────────────────────────────────
def fmt(n: float) -> str:
    return f"{n:,}"


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def open_ro(p: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def explain(con: sqlite3.Connection, sql: str) -> list[str]:
    return [" | ".join(str(x) for x in r)
            for r in con.execute("EXPLAIN QUERY PLAN " + sql)]


def timed(con: sqlite3.Connection, sql: str, repeat: int = 2) -> dict:
    best, rows = 1e9, 0
    for _ in range(repeat):
        t0 = time.perf_counter()
        n = 0
        for _r in con.execute(sql):
            n += 1
        best = min(best, time.perf_counter() - t0)
        rows = n
    return {"ms": round(best * 1000, 1), "rows": rows, "plan": explain(con, sql)}


def db_size(con: sqlite3.Connection) -> dict:
    page = con.execute("PRAGMA page_size").fetchone()[0]
    pages = con.execute("PRAGMA page_count").fetchone()[0]
    free = con.execute("PRAGMA freelist_count").fetchone()[0]
    return {"page_size": page, "page_count": pages, "freelist_pages": free,
            "freelist_bytes": free * page, "db_bytes": pages * page}


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", s)


def lev(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 3:
        return 99
    d = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, d[0] = d[0], i
        for j, cb in enumerate(b, 1):
            t = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (ca != cb))
            prev = t
    return d[len(b)]


def write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ── 审计：PRAGMA / FK / VACUUM / 索引 / EXPLAIN ─────────────────────
def audit_pragmas(con: sqlite3.Connection) -> dict:
    out = {p: con.execute(f"PRAGMA {p}").fetchone()[0]
           for p in ("page_size", "page_count", "freelist_count", "journal_mode",
                     "auto_vacuum", "foreign_keys", "cache_size", "encoding")}
    out.update(db_size(con))
    out["freelist_pct"] = round(100 * out["freelist_bytes"] / out["db_bytes"], 2)
    return out


def audit_fk(con: sqlite3.Connection) -> dict:
    rows = [tuple(r) for r in con.execute("PRAGMA foreign_key_check")]
    detail = []
    for table, rowid, parent, _fkid in rows:
        item = {"table": table, "rowid": rowid, "parent": parent}
        if table == "ingest_run":
            r = con.execute("SELECT run_id, source_id, status FROM ingest_run WHERE rowid=?",
                            (rowid,)).fetchone()
            if r:
                item.update({"run_id": r["run_id"], "source_id": r["source_id"],
                             "status": r["status"],
                             "fix_sql": f"INSERT INTO source (source_id, name) VALUES "
                                        f"('{r['source_id']}', '<补来源名>'); -- 历史 ingest 元数据"})
        detail.append(item)
    return {"count": len(rows), "rows": detail}


def audit_stats(con: sqlite3.Connection) -> dict:
    has = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_stat1'"
                      ).fetchone()[0] > 0
    rows = con.execute("SELECT COUNT(*) FROM sqlite_stat1").fetchone()[0] if has else 0
    return {"sqlite_stat1": has, "stat_rows": rows,
            "warning": ("已有 ANALYZE 统计：本库实测统计会让 build 查询显著变慢，建议保持无统计"
                        if has else None)}


def audit_indexes(con: sqlite3.Connection) -> dict:
    items = [{"name": r["name"], "table": r["tbl_name"],
              "sql": (r["sql"] or "(auto/unique)")}
             for r in con.execute("SELECT name, tbl_name, sql FROM sqlite_master"
                                  " WHERE type='index' ORDER BY tbl_name, name")]
    return {"count": len(items), "items": items}


def audit_vacuum(con: sqlite3.Connection) -> dict:
    s = db_size(con)
    free = s["freelist_bytes"]
    return {**s,
            "freelist_pct": round(100 * free / s["db_bytes"], 2),
            "est_reclaim_bytes": free,
            "est_reclaim_pct": round(100 * free / s["db_bytes"], 2),
            "recommend": free > s["db_bytes"] * 0.05,
            "note": "VACUUM 需要约等于 DB 大小的空闲磁盘 + 独占锁；实测本库 6.16 s、"
                    "450,396,160 → 322,768,896 B（-127.6 MB / -28.3%），quick_check ok，查询不变慢"}


def audit_queries(con: sqlite3.Connection) -> dict:
    out = {}
    for label, sql in BENCH.items():
        out[label] = timed(con, sql, repeat=1 if label == "load_index_main" else 2)
    return out


def table_counts(con: sqlite3.Connection) -> dict:
    out = {}
    for t in ("product", "product_component", "product_name", "name_variant",
              "name_key", "variant", "substance", "artg_entry", "source",
              "ingest_run", "dose_warning"):
        try:
            out[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            out[t] = None
    return out


# ── 审计：27 对重复成分 ─────────────────────────────────────────────
def component_counts(con: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for r in con.execute("""SELECT v.substance_id, COUNT(*) n
                            FROM product_component pc JOIN variant v
                              ON v.variant_id = pc.variant_id
                            GROUP BY v.substance_id"""):
        out[r[0]] = r[1]
    return dict(out)


def audit_duplicates(con: sqlite3.Connection, comp: dict[str, int]) -> dict:
    """复刻 etl/auto_merge_substances.py 判据：同 ATC 前 5 位 + 归一化名相同或中文名相同。"""
    rows = [dict(r) for r in con.execute(
        "SELECT substance_id, inn_en, inn_zh, atc FROM substance")]
    by_atc: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["atc"] and len(r["atc"]) >= 5:
            by_atc[r["atc"][:5]].append(r)
    mergeable, keep = [], []
    for atc, group in by_atc.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                na, nb = norm_name(a["inn_en"]), norm_name(b["inn_en"])
                if not na or not nb:
                    continue
                if na == nb or (a["inn_zh"] and a["inn_zh"] == b["inn_zh"]):
                    canon, dup = (a, b) if comp.get(a["substance_id"], 0) >= comp.get(
                        b["substance_id"], 0) else (b, a)
                    mergeable.append({
                        "atc4": atc, "canonical": canon["substance_id"],
                        "canonical_name": canon["inn_en"], "dup": dup["substance_id"],
                        "dup_name": dup["inn_en"],
                        "canonical_components": comp.get(canon["substance_id"], 0),
                        "dup_components": comp.get(dup["substance_id"], 0),
                        "reason": "inn 归一化相同" if na == nb else "中文名相同"})
                elif abs(len(na) - len(nb)) <= 3 and lev(na, nb) <= 2:
                    keep.append({"atc4": atc, "a": a["substance_id"], "a_name": a["inn_en"],
                                 "b": b["substance_id"], "b_name": b["inn_en"],
                                 "lev": lev(na, nb),
                                 "reason": "同 ATC-4 名字相近但不是同一写法（可能盐/酯不同）"})
    ids = {p["canonical"] for p in mergeable} | {p["dup"] for p in mergeable}
    return {"mergeable_pairs": mergeable, "mergeable_ids": len(ids),
            "keep_similar": keep,
            "note": "mergeable 清单只读输出；真正合并是独立任务（需人确认 + 改 product_component 指向）"}


# ── 审计：同盐 variant 歧义（1,305 组件那类） ──────────────────────
def audit_salt_variants(con: sqlite3.Connection) -> dict:
    sys.path.insert(0, str(ROOT / "etl"))
    try:
        from normalize_salts import ANHYDROUS_TOKENS, WATER_TOKENS, classify_salt
    except Exception as e:                                  # pragma: no cover
        return {"error": f"无法导入 etl/normalize_salts.py: {e}"}

    def waters_of(text: str) -> tuple[tuple[str, ...], bool]:
        toks = [t for t in (text or "").lower().replace(",", " ").split() if t]
        return (tuple(sorted({t for t in toks if t in WATER_TOKENS})),
                any(t in ANHYDROUS_TOKENS for t in toks))

    variants = [dict(r) for r in con.execute(
        "SELECT variant_id, substance_id, salt, salt_code, hydrate, ester, base_fraction"
        " FROM variant")]
    by_sid: dict[str, list[dict]] = defaultdict(list)
    for v in variants:
        by_sid[v["substance_id"]].append(v)
    groups = []
    for sid, arr in by_sid.items():
        bucket: dict[tuple, list[dict]] = defaultdict(list)
        for v in arr:
            code = v["salt_code"] or classify_salt(v["salt"] or "").salt_code
            bucket[(code, waters_of((v["salt"] or "") + " " + (v["hydrate"] or "")))].append(v)
        for (code, (waters, anhydrous)), cands in bucket.items():
            if len(cands) > 1:
                groups.append({"substance_id": sid, "salt_code": code,
                               "waters": list(waters), "anhydrous": anhydrous,
                               "variants": cands})
    comp: dict[str, int] = {}
    if groups:
        ids = [v["variant_id"] for g in groups for v in g["variants"]]
        q = ",".join("?" * len(ids))
        comp = {r[0]: r[1] for r in con.execute(
            f"SELECT variant_id, COUNT(*) FROM product_component"
            f" WHERE variant_id IN ({q}) GROUP BY variant_id", tuple(ids))}
    gb_comp = {r[0]: r[1] for r in con.execute(
        """SELECT pc.variant_id, COUNT(*) FROM product_component pc
           JOIN product p ON p.product_id = pc.product_id
           WHERE p.country = 'GB' AND p.source_id = 'dmd' GROUP BY pc.variant_id""")}

    merge_groups, keep_groups = [], []
    for g in groups:
        generic = g["salt_code"] in ("", "non_salt", "mixed")
        differ = (len({round(v["base_fraction"], 6) for v in g["variants"]}) > 1
                  or len({v["ester"] for v in g["variants"]}) > 1)
        item = {"substance_id": g["substance_id"], "salt_code": g["salt_code"],
                "waters": g["waters"], "anhydrous": g["anhydrous"],
                "variants": g["variants"]}
        if generic:
            item["reason"] = ("salt_code 是 generic（''/non_salt/mixed）——共享编码不代表同盐，"
                              "如 fluticasone propionate vs furoate，**必须保留**")
            keep_groups.append(item)
        elif differ:
            item["reason"] = "base_fraction / ester 不一致（语义不同）——必须保留"
            keep_groups.append(item)
        else:
            item["reason"] = "同 substance + 同 salt_code + 同水合物（含 anhydrous 标记）+ 同 ester/基准 → 可合并"
            merge_groups.append(item)
    for g in merge_groups + keep_groups:
        for v in g["variants"]:
            v["components"] = comp.get(v["variant_id"], 0)
            v["gb_components"] = gb_comp.get(v["variant_id"], 0)
        g["total_components"] = sum(v["components"] for v in g["variants"])
        g["gb_components"] = sum(v["gb_components"] for v in g["variants"])
        g["variant_ids"] = [v["variant_id"] for v in g["variants"]]
    merge_groups.sort(key=lambda g: -g["total_components"])
    keep_groups.sort(key=lambda g: -g["total_components"])
    for g in merge_groups:                          # 合并计划：留组件最多的当 canonical
        vs = sorted(g["variants"], key=lambda v: -v["components"])
        g["canonical"] = vs[0]["variant_id"]
        g["dups"] = [{"variant_id": v["variant_id"], "salt": v["salt"],
                      "hydrate": v["hydrate"], "components": v["components"]}
                     for v in vs[1:]]
    return {
        "ambiguous_groups": len(groups),
        "ambiguous_variants": sum(len(g["variants"]) for g in groups),
        "mergeable_groups": len(merge_groups),
        "mergeable_variants": sum(len(g["variants"]) for g in merge_groups),
        "mergeable_components": sum(g["total_components"] for g in merge_groups),
        "mergeable_gb_components": sum(g["gb_components"] for g in merge_groups),
        "keep_group_count": len(keep_groups),
        "keep_variants": sum(len(g["variants"]) for g in keep_groups),
        "keep_components": sum(g["total_components"] for g in keep_groups),
        "merge_groups": merge_groups,
        "keep_groups": keep_groups,
        "note": "reports/gb-salt-recovery.md §6.2 的 1,305 组件是当时 GB-dmd 侧被「同盐多 variant」"
                "卡住的量；本库已应用 GB 盐型恢复，现存 GB 暴露已大幅下降（见 mergeable_gb_components）",
    }


def run_audit(con: sqlite3.Connection, full_integrity: bool) -> dict:
    t0 = time.perf_counter()
    print("== PRAGMA / integrity ==", flush=True)
    pragmas = audit_pragmas(con)
    t = time.perf_counter()
    integrity = con.execute("PRAGMA integrity_check" if full_integrity else "PRAGMA quick_check"
                            ).fetchone()[0]
    integrity_s = round(time.perf_counter() - t, 2)
    print(f"  {('integrity_check' if full_integrity else 'quick_check')}: {integrity}"
          f"（{integrity_s}s）", flush=True)
    print("== foreign_key_check ==", flush=True)
    fk = audit_fk(con)
    print(f"  violations: {fk['count']}", flush=True)
    stats, indexes, vacuum = audit_stats(con), audit_indexes(con), audit_vacuum(con)
    counts = table_counts(con)
    print("== EXPLAIN / 计时（无索引改动）==", flush=True)
    queries = audit_queries(con)
    for label, r in queries.items():
        print(f"  {label:22} {r['ms']:>9.1f} ms rows={r['rows']:>7}  "
              + " | ".join(r["plan"])[:120], flush=True)
    print("== 重复成分审计 ==", flush=True)
    duplicates = audit_duplicates(con, component_counts(con))
    print(f"  mergeable pairs: {len(duplicates['mergeable_pairs'])}"
          f" / ids {duplicates['mergeable_ids']} / keep-similar {len(duplicates['keep_similar'])}",
          flush=True)
    print("== 同盐 variant 歧义审计 ==", flush=True)
    salts = audit_salt_variants(con)
    print(f"  groups {salts.get('ambiguous_groups')}；"
          f"可合并 {salts.get('mergeable_groups')} 组 / {salts.get('mergeable_variants')} variant"
          f" / {salts.get('mergeable_components')} 组件", flush=True)
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "db": str(DB), "db_bytes": DB.stat().st_size,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "pragmas": pragmas, "integrity": {"mode": "full" if full_integrity else "quick",
                                          "result": integrity, "s": integrity_s},
        "foreign_key_check": fk, "stats": stats, "indexes": indexes,
        "vacuum": vacuum, "table_counts": counts,
        "queries": queries,
        "recommended_indexes": RECOMMENDED, "optional_indexes": OPTIONAL,
        "rejected_candidates": REJECTED,
        "duplicates": duplicates, "salt_variants": salts,
    }


def export_audit(audit: dict, out_dir: Path) -> dict:
    """把审计清单落成 CSV/JSON，返回写入的文件列表。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    ts = datetime.now().strftime("%Y-%m-%d")
    audit_json = out_dir / f"audit-{ts}.json"
    audit_json.write_text(json.dumps(audit, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8")
    files.append(str(audit_json.relative_to(ROOT)))
    dup = audit["duplicates"]
    write_csv(out_dir / "duplicate_substances_merge.csv",
              ["atc4", "canonical", "canonical_name", "canonical_components",
               "dup", "dup_name", "dup_components", "reason"],
              dup["mergeable_pairs"])
    files.append(str((out_dir / "duplicate_substances_merge.csv").relative_to(ROOT)))
    write_csv(out_dir / "duplicate_substances_keep_similar.csv",
              ["atc4", "a", "a_name", "b", "b_name", "lev", "reason"],
              dup["keep_similar"])
    files.append(str((out_dir / "duplicate_substances_keep_similar.csv").relative_to(ROOT)))
    merge_rows, keep_rows = [], []
    for g in audit["salt_variants"].get("merge_groups", []):
        for d in g["dups"]:
            merge_rows.append({"substance_id": g["substance_id"],
                               "salt_code": g["salt_code"],
                               "waters": "+".join(g["waters"]) or "-",
                               "anhydrous": g["anhydrous"],
                               "canonical": g["canonical"],
                               "dup_variant": d["variant_id"],
                               "dup_salt": d["salt"],
                               "dup_components": d["components"],
                               "group_components": g["total_components"]})
    merge_rows.sort(key=lambda r: -r["group_components"])
    write_csv(out_dir / "salt_variant_merge.csv",
              ["substance_id", "salt_code", "waters", "anhydrous", "canonical",
               "dup_variant", "dup_salt", "dup_components", "group_components"], merge_rows)
    files.append(str((out_dir / "salt_variant_merge.csv").relative_to(ROOT)))
    for g in audit["salt_variants"].get("keep_groups", []):
        keep_rows.append({"substance_id": g["substance_id"], "salt_code": g["salt_code"],
                          "waters": "+".join(g["waters"]) or "-", "anhydrous": g["anhydrous"],
                          "variant_ids": ";".join(g["variant_ids"]),
                          "components": g["total_components"], "reason": g["reason"]})
    write_csv(out_dir / "salt_variant_keep.csv",
              ["substance_id", "salt_code", "waters", "anhydrous", "variant_ids",
               "components", "reason"], keep_rows)
    files.append(str((out_dir / "salt_variant_keep.csv").relative_to(ROOT)))
    return {"files": files}


# ── dry-run ──────────────────────────────────────────────────────────
def cmd_dry_run(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"FATAL: DB 不存在: {db_path}", file=sys.stderr)
        return 1
    con = open_ro(db_path)
    try:
        audit = run_audit(con, args.full_integrity)
    finally:
        con.close()
    audit["db"] = str(db_path.resolve().relative_to(ROOT)) if db_path.resolve().is_relative_to(ROOT) \
        else str(db_path)
    exports = export_audit(audit, TMP)
    audit["exports"] = exports
    if args.json_out:
        p = Path(args.json_out)
        p.write_text(json.dumps(audit, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"JSON: {p}", flush=True)
    print("\n== 结论 ==")
    v = audit["vacuum"]
    print(f"  索引现况   : {audit['indexes']['count']} 个；建议新增 {len(RECOMMENDED)} 个"
          f"（可选 {len(OPTIONAL)} 个，实测否决 {len(REJECTED)} 类写法，见报告）")
    print(f"  统计信息   : {'已有 ANALYZE 统计（危险）' if audit['stats']['sqlite_stat1'] else '无 sqlite_stat1（当前最优，勿跑 ANALYZE）'}")
    print(f"  FK 违规    : {audit['foreign_key_check']['count']} 行"
          + (f" → {json.dumps(audit['foreign_key_check']['rows'], ensure_ascii=False)}"
             if audit['foreign_key_check']['count'] else ""))
    print(f"  VACUUM     : 空闲 {fmt(v['freelist_bytes'])} B（{v['freelist_pct']}% of DB）"
          f" → {'建议收集' if v['recommend'] else '暂不需要'}，预计回收 ~{fmt(v['est_reclaim_bytes'])} B")
    print(f"  重复成分   : 可合并 {len(audit['duplicates']['mergeable_pairs'])} 对 / "
          f"{audit['duplicates']['mergeable_ids']} 个 id；需保留(名字相近) {len(audit['duplicates']['keep_similar'])} 对")
    s = audit["salt_variants"]
    if "error" not in s:
        print(f"  同盐 variant: 歧义 {s['ambiguous_groups']} 组 / {s['ambiguous_variants']} 个；"
              f"可合并 {s['mergeable_groups']} 组 / {s['mergeable_variants']} 个 / "
              f"{fmt(s['mergeable_components'])} 组件；保留 {s['keep_group_count']} 组")
    print(f"\n审计明细: {', '.join(exports['files'])}")
    print("（dry-run 只读；索引/ VACUUM 变更请用 --apply，且只作用在 .tmp/db-opt/work.db 副本）")
    return 0


# ── apply（仅副本） ─────────────────────────────────────────────────
def _guard_copy_path(copy_path: Path) -> None:
    real = DB.resolve()
    if copy_path.resolve() == real:
        raise SystemExit("拒绝在真实库上 apply/rollback：请用副本（默认 .tmp/db-opt/work.db）")
    if copy_path.resolve() == ROOT / "data" / "drugs.db":
        raise SystemExit("拒绝在真实库上操作")


def _indexes_for(args: argparse.Namespace) -> list[dict]:
    idx = list(RECOMMENDED)
    if args.include_optional:
        idx += OPTIONAL
    return idx


def cmd_apply(args: argparse.Namespace) -> int:
    copy_path = Path(args.copy)
    _guard_copy_path(copy_path)
    if not DB.is_file():
        print(f"FATAL: DB 不存在: {DB}", file=sys.stderr)
        return 1
    TMP.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    print(f"复制 {DB.name} ({fmt(DB.stat().st_size)} B) → {copy_path}", flush=True)
    shutil.copy2(DB, copy_path)
    copy_sha = file_sha256(copy_path)
    indexes = _indexes_for(args)
    con = sqlite3.connect(copy_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        size_before = db_size(con)
        integrity_before = con.execute("PRAGMA quick_check").fetchone()[0]
        print("基准（before）…", flush=True)
        bench_before = {k: timed(con, BENCH[k], repeat=1 if k == "load_index_main" else 2)
                        for k in BENCH_APPLY}
        created, build_times = [], {}
        for item in indexes:
            ts = time.perf_counter()
            con.execute(item["sql"])
            con.commit()
            build_times[item["name"]] = round(time.perf_counter() - ts, 3)
            created.append(item["name"])
            print(f"  建索引 {item['name']}: {build_times[item['name']]}s", flush=True)
        vacuum_info = None
        if args.vacuum:
            vb = db_size(con)
            ts = time.perf_counter()
            con.execute("VACUUM")
            vacuum_info = {"time_s": round(time.perf_counter() - ts, 2),
                           "before_bytes": vb["db_bytes"], "after_bytes": db_size(con)["db_bytes"],
                           "saved_bytes": vb["db_bytes"] - db_size(con)["db_bytes"]}
            print(f"  VACUUM: {vacuum_info['time_s']}s，"
                  f"{fmt(vacuum_info['before_bytes'])} → {fmt(vacuum_info['after_bytes'])} B", flush=True)
        analyze_info = None
        if args.analyze:
            print("  !! 运行 ANALYZE（实测会让 build 查询显著变慢，仅用于复现实验）", flush=True)
            ts = time.perf_counter()
            con.execute("ANALYZE")
            con.commit()
            analyze_info = {"time_s": round(time.perf_counter() - ts, 2)}
        print("基准（after）…", flush=True)
        bench_after = {k: timed(con, BENCH[k], repeat=1 if k == "load_index_main" else 2)
                       for k in BENCH_APPLY}
        integrity_after = con.execute("PRAGMA quick_check").fetchone()[0]
        fk_after = len([r for r in con.execute("PRAGMA foreign_key_check")])
        size_after = db_size(con)
        manifest = {
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "status": "applied",
            "source_db": str(DB.relative_to(ROOT)),
            "source_mtime": datetime.fromtimestamp(DB.stat().st_mtime).isoformat(timespec="seconds"),
            "copy": str(copy_path.relative_to(ROOT)) if copy_path.resolve().is_relative_to(ROOT)
                    else str(copy_path),
            "copy_sha256": copy_sha,
            "created_indexes": [{"name": i["name"], "sql": i["sql"], "build_s": build_times[i["name"]]}
                                for i in indexes if i["name"] in build_times],
            "vacuum": vacuum_info,
            "analyze": analyze_info,
            "db_bytes_before": size_before["db_bytes"],
            "db_bytes_after": size_after["db_bytes"],
            "integrity_before": integrity_before,
            "integrity_after": integrity_after,
            "foreign_key_violations_after": fk_after,
            "bench_before": bench_before,
            "bench_after": bench_after,
            "elapsed_s": round(time.perf_counter() - t0, 2),
        }
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
    finally:
        con.close()
    print("\n== apply 结果（副本）==")
    print(f"  索引: {', '.join(created)}")
    print(f"  DB: {fmt(size_before['db_bytes'])} → {fmt(size_after['db_bytes'])} B"
          f"（{fmt(size_after['db_bytes'] - size_before['db_bytes'])} B）")
    if vacuum_info:
        print(f"  VACUUM: -{fmt(vacuum_info['saved_bytes'])} B")
    print(f"  quick_check: {integrity_before} → {integrity_after}；FK 违规 {fk_after}")
    for k in BENCH_APPLY:
        b, a = bench_before[k], bench_after[k]
        delta = a["ms"] - b["ms"]
        print(f"  {k:22} {b['ms']:>9.1f} → {a['ms']:>9.1f} ms ({delta:+.1f})")
    print(f"  manifest: {MANIFEST.relative_to(ROOT)}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                                       encoding="utf-8")
    return 0 if integrity_after == "ok" else 1


# ── rollback（仅副本） ──────────────────────────────────────────────
def cmd_rollback(args: argparse.Namespace) -> int:
    if not MANIFEST.is_file():
        print(f"FATAL: 没有 manifest {MANIFEST}（先跑 --apply）", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    copy_path = Path(args.copy)
    if manifest.get("copy"):
        recorded = ROOT / manifest["copy"] if not Path(manifest["copy"]).is_absolute() \
            else Path(manifest["copy"])
        if copy_path == COPY:
            copy_path = recorded
    _guard_copy_path(copy_path)
    if not copy_path.is_file():
        print(f"FATAL: 副本不存在 {copy_path}", file=sys.stderr)
        return 1
    con = sqlite3.connect(copy_path)
    try:
        dropped = []
        for item in manifest.get("created_indexes", []):
            con.execute(f"DROP INDEX IF EXISTS {item['name']}")
            dropped.append(item["name"])
            print(f"  drop {item['name']}", flush=True)
        con.commit()
        integrity = con.execute("PRAGMA quick_check").fetchone()[0]
        size = db_size(con)
        manifest["rollback"] = {
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "dropped": dropped, "quick_check": integrity, "db_bytes": size["db_bytes"],
        }
        manifest["status"] = "rolled_back"
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
    finally:
        con.close()
    print(f"\n== rollback 完成（副本 {copy_path}）==")
    print(f"  已删除 {len(dropped)} 个索引；quick_check={integrity}；DB {fmt(size['db_bytes'])} B")
    return 0 if integrity == "ok" else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="数据库优化审计 + 索引建议（真实库只读，变更只在副本）")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只读审计（默认）")
    mode.add_argument("--apply", action="store_true", help="在副本上建索引（+可选 VACUUM）并跑前后基准")
    mode.add_argument("--rollback", action="store_true", help="按 manifest 删除副本上的索引")
    ap.add_argument("--db", default=str(DB), help="源 DB（默认 data/drugs.db，只读）")
    ap.add_argument("--copy", default=str(COPY), help="apply/rollback 使用的副本路径")
    ap.add_argument("--full-integrity", action="store_true", help="用 integrity_check（慢）")
    ap.add_argument("--vacuum", action="store_true", help="apply 时在副本上 VACUUM")
    ap.add_argument("--analyze", action="store_true", help="apply 时跑 ANALYZE（仅复现实验，会被基线对比）")
    ap.add_argument("--include-optional", action="store_true", help="连可选索引一起建")
    ap.add_argument("--json-out", default="", help="额外输出 JSON 文件")
    args = ap.parse_args(argv)
    if args.db and Path(args.db).resolve() != DB.resolve():
        print(f"NOTE: --db={args.db}（只读审计用；apply 仍从默认 data/drugs.db 复制）", file=sys.stderr)
    TMP.mkdir(parents=True, exist_ok=True)
    if args.apply:
        return cmd_apply(args)
    if args.rollback:
        return cmd_rollback(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
