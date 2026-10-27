#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把「只有西语名」的 ES/MX 专属成分（substance_id = mx-es-* 或 ES/MX 独有的西语 id）
合并到已有的英文 INN 成分。

用法
----
    # 默认 dry-run：只读打开数据库，打印将合并的 id 对、组件数、跳过原因
    python etl/merge_es_substances.py

    # 真正写库（事务内 UPDATE product_component、DELETE variant/substance）
    python etl/merge_es_substances.py --apply

    # 非 mx-es- 前缀的 ES 专属 id（CIMA 侧未映射西语名）：默认只报告，不动
    python etl/merge_es_substances.py --include-unprefixed --dry-run
    python etl/merge_es_substances.py --include-unprefixed --apply

    # 用撤销清单回滚（缺省取 .tmp/es-map/ 下最新的 merge_undo_*.json）
    python etl/merge_es_substances.py --rollback
    python etl/merge_es_substances.py --rollback .tmp/es-map/merge_undo_xxx.json

输入
----
`data/es_inn_overrides.csv`（UTF-8，可带 BOM），列：
    es_name,en_inn,es_substance_id,en_substance_id,evidence,confidence,status,reason
只有 status == "mergeable" 的行会被处理；no_english / combination / uncertain 只统计。

安全校验（任何一条不过就跳过该行，绝不部分合并）
------------------------------------------------
1. ES 侧 substance 存在；id 以 mx-es- 开头（默认模式）——本工具永不删英文成分
2. 非 mx-es- 前缀的源（--include-unprefixed 时）：其全部产品必须只在 ES/MX 市场
3. 英文目标 substance 存在、不以 mx-es-/cn- 开头、inn_en 有拉丁字母、
   并与 CSV 的 en_inn 归一化后一致
4. ES 侧恰好 1 个 variant，且 salt/hydrate/ester 全空（base variant），base_fraction≈1
5. 英文目标有 base variant；若 ES 名里带盐（clorhidrato/bromuro/de sodio…），
   优先挂到 salt 匹配的英文 variant，否则挂 base variant
6. ES 侧成分没有被 nickname / drug_term / confusable_pair / dose_warning（若表存在）引用
7. 将被移动的产品没有 corroboration 记录（人工核对过的产品保持原样）
8. 幂等：ES 成分已不存在（上一轮已合并）→ already_merged，不报错
9. CSV 内同一 es_substance_id 出现多次且目标不一致 → 全部跳过

撤销清单
--------
--apply 在提交前把完整的 substance 行、variant 行、被移动的 product_component
(product_id, ord, 旧 variant_id) 写入 JSON（默认 .tmp/es-map/merge_undo_<UTC>.json），
并写入 committed 标记；--rollback 按清单逆序重建并按 (product_id, ord) 精确回挂。
清单自身可重复回滚（第二次会全部记为 already_restored）。

注意：本轮验证只在 .tmp/es-map/ 的 DB 副本上跑 --apply；正式库请先 --dry-run。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_DEFAULT = ROOT / "data" / "drugs.db"
CSV_DEFAULT = ROOT / "data" / "es_inn_overrides.csv"
MANIFEST_DIR = ROOT / ".tmp" / "es-map"

CSV_COLUMNS = ["es_name", "en_inn", "es_substance_id", "en_substance_id",
               "evidence", "confidence", "status", "reason"]
PROCESS_STATUS = "mergeable"

# ES 名里的盐 → 英文 variant.salt 里应出现的关键词
SALT_ES_EN = [
    ("clorhidrato", "hydrochloride"), ("hidrocloruro", "hydrochloride"),
    ("bromuro", "bromide"), ("bromhidrato", "hydrobromide"),
    ("de sodio", "sodium"), ("sodico", "sodium"), ("sodica", "sodium"),
    ("de potasio", "potassium"), ("potasico", "potassium"), ("potasica", "potassium"),
    ("de calcio", "calcium"), ("calcico", "calcium"), ("calcica", "calcium"),
    ("de magnesio", "magnesium"), ("magnesico", "magnesium"),
    ("dipropionato", "dipropionate"), ("propionato", "propionate"),
    ("acetato", "acetate"), ("succinato", "succinate"), ("maleato", "maleate"),
    ("fumarato", "fumarate"), ("citrato", "citrate"), ("besilato", "besylate"),
    ("mesilato", "mesylate"), ("tosilato", "tosylate"), ("fosfato", "phosphate"),
    ("sulfato", "sulfate"), ("tartrato", "tartrate"), ("lactato", "lactate"),
    ("gluconato", "gluconate"), ("carbonato", "carbonate"), ("nitrato", "nitrate"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deacc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if not unicodedata.combining(c))


def norm_name(s: str) -> str:
    s = deacc(s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def has_latin(s: str) -> bool:
    return bool(re.search(r"[A-Za-z]", s or ""))


# ---------------------------------------------------------------------------
def load_csv(path: Path) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    if not path.exists():
        return [], [f"CSV 不存在: {path}"]
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        header = reader.fieldnames or []
    missing = [c for c in CSV_COLUMNS if c not in header]
    if missing:
        return [], [f"CSV 缺列: {', '.join(missing)} (实际: {header})"]
    for r in rows:
        for c in CSV_COLUMNS:
            r[c] = (r.get(c) or "").strip()
    by_es: dict[str, list[dict]] = {}
    for r in rows:
        if r["es_substance_id"]:
            by_es.setdefault(r["es_substance_id"], []).append(r)
    out: list[dict] = []
    for es_id, group in by_es.items():
        targets = {r["en_substance_id"] for r in group if r["status"] == PROCESS_STATUS}
        if len(targets) > 1:
            errors.append(f"{es_id} 出现 {len(group)} 次且目标不一致: {sorted(targets)}")
            continue
        r = dict(group[0])
        if len(group) > 1:
            r["_csv_dups"] = len(group)
        out.append(r)
    return out, errors


def connect(db_path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = "file:" + str(db_path.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=60)
    else:
        con = sqlite3.connect(str(db_path), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                       (name,)).fetchone() is not None


def base_variants(con, substance_id: str) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT * FROM variant WHERE substance_id=?
           AND COALESCE(salt,'')='' AND COALESCE(hydrate,'')='' AND COALESCE(ester,'')=''""",
        (substance_id,)).fetchall()


def all_variants(con, substance_id: str) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM variant WHERE substance_id=?",
                       (substance_id,)).fetchall()


def salt_variant(con, target_sid: str, es_name: str) -> sqlite3.Row | None:
    """ES 名里带盐 → 找英文目标里 salt 匹配的 variant（唯一才用）。"""
    n = norm_name(es_name)
    wants = [en for es, en in SALT_ES_EN if es in n]
    if not wants:
        return None
    hits = []
    for v in all_variants(con, target_sid):
        salt = (v["salt"] or "").lower()
        if salt and any(w in salt for w in wants):
            hits.append(v)
    return hits[0] if len(hits) == 1 else None


def product_markets(con, sid: str) -> set[str]:
    rows = con.execute(
        """SELECT DISTINCT p.country FROM product p
           JOIN product_component pc ON pc.product_id=p.product_id
           JOIN variant v ON v.variant_id=pc.variant_id
           WHERE v.substance_id=?""", (sid,)).fetchall()
    return {r[0] for r in rows if r[0]}


def ref_counts(con, es_sid: str, variant_ids: list[str]) -> dict[str, int]:
    out = {"nickname": 0, "drug_term": 0, "confusable_pair": 0, "dose_warning": 0,
           "corroboration_products": 0}
    out["nickname"] = con.execute(
        "SELECT COUNT(*) FROM nickname WHERE substance_id=?", (es_sid,)).fetchone()[0]
    if table_exists(con, "drug_term"):
        out["drug_term"] = con.execute(
            "SELECT COUNT(*) FROM drug_term WHERE substance_id=?", (es_sid,)).fetchone()[0]
    out["confusable_pair"] = con.execute(
        "SELECT COUNT(*) FROM confusable_pair WHERE a_substance_id=? OR b_substance_id=?",
        (es_sid, es_sid)).fetchone()[0]
    if table_exists(con, "dose_warning"):
        out["dose_warning"] = con.execute(
            "SELECT COUNT(*) FROM dose_warning WHERE substance_id=? OR related_substance_id=?",
            (es_sid, es_sid)).fetchone()[0]
    if variant_ids:
        qs = ",".join("?" * len(variant_ids))
        out["corroboration_products"] = con.execute(
            f"""SELECT COUNT(DISTINCT c.product_id) FROM corroboration c
                WHERE EXISTS (SELECT 1 FROM product_component pc
                              WHERE pc.product_id=c.product_id AND pc.variant_id IN ({qs}))""",
            variant_ids).fetchone()[0]
    return out


# ---------------------------------------------------------------------------
def plan(con, rows: list[dict], include_unprefixed: bool, verbose: bool = False) -> dict:
    status_counts = Counter(r["status"] for r in rows)
    accepted: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    for r in rows:
        if r["status"] != PROCESS_STATUS:
            continue
        es_sid = r["es_substance_id"]
        en_sid = r["en_substance_id"]
        why, level = None, "skip"

        es_row = con.execute("SELECT * FROM substance WHERE substance_id=?", (es_sid,)).fetchone()
        en_row = con.execute("SELECT * FROM substance WHERE substance_id=?", (en_sid,)).fetchone() \
            if en_sid else None

        if not es_sid.startswith("mx-es-"):
            if not include_unprefixed:
                why = "非 mx-es- 前缀（需 --include-unprefixed）"
            elif not es_row:
                why = "already_merged（ES 成分已不存在）"
            else:
                mk = product_markets(con, es_sid)
                if mk - {"ES", "MX"}:
                    why, level = f"非前缀源的跨市场成分 {sorted(mk)}，拒绝删除", "error"
        if why is None and not es_row:
            why = "already_merged（ES 成分已不存在）"
        if why is None and not en_sid:
            why, level = "en_substance_id 为空", "error"
        if why is None and not en_row:
            why, level = f"英文目标不存在: {en_sid}", "error"
        if why is None and (en_sid.startswith(("mx-es-", "cn-")) or not has_latin(en_row["inn_en"])):
            why, level = f"英文目标 id/inn 非法: {en_sid} {en_row['inn_en']!r}", "error"
        if why is None and norm_name(en_row["inn_en"]) != norm_name(r["en_inn"]):
            why, level = (f"en_inn 不一致: CSV={r['en_inn']!r} DB={en_row['inn_en']!r}", "error")
        if why is None and en_sid == es_sid:
            why, level = "ES 与 EN 目标相同", "error"

        es_vars = all_variants(con, es_sid) if es_row else []
        en_base = base_variants(con, en_sid) if en_row else []
        if why is None and len(es_vars) != 1:
            why = f"ES 侧 variant 数={len(es_vars)}（要求恰好 1 个）"
        if why is None:
            v = es_vars[0]
            salt, hyd, est = (v["salt"] or ""), (v["hydrate"] or ""), (v["ester"] or "")
            if salt or hyd or est:
                why = f"ES 侧不是 base variant: salt={salt!r} hydrate={hyd!r} ester={est!r}"
            elif abs((v["base_fraction"] if v["base_fraction"] is not None else 1.0) - 1.0) > 1e-9:
                why = f"ES 侧 base_fraction={v['base_fraction']}（要求 1.0）"
        if why is None and len(en_base) > 1:
            why = f"英文目标 base variant 数={len(en_base)}（要求至多 1 个）"
        if why is None and es_vars and en_row:
            refs = ref_counts(con, es_sid, [es_vars[0]["variant_id"]])
            for k in ("nickname", "drug_term", "confusable_pair", "dose_warning"):
                if refs.get(k):
                    why = f"{k} 引用 {refs[k]} 条"
                    break
            if why is None and refs["corroboration_products"]:
                why = f"受影响产品有 corroboration {refs['corroboration_products']} 条"

        if why is not None:
            (errors if level == "error" else skipped).append(dict(
                es_sid=es_sid, en_sid=en_sid, es=r["es_name"], en=r["en_inn"], reason=why))
            continue

        en_v = salt_variant(con, en_sid, r["es_name"])
        if en_v is not None:
            target_kind = "salt"
        else:
            if not en_base:
                skipped.append(dict(es_sid=es_sid, en_sid=en_sid, es=r["es_name"],
                                    en=r["en_inn"], reason="英文目标没有 base variant 可挂"))
                continue
            en_v = en_base[0]
            target_kind = "base"
        pcs = con.execute(
            "SELECT product_id, ord, variant_id FROM product_component WHERE variant_id=?"
            " ORDER BY product_id, ord", (es_vars[0]["variant_id"],)).fetchall()
        accepted.append(dict(
            es_name=r["es_name"], en_inn=r["en_inn"],
            es_sid=es_sid, en_sid=en_sid,
            es_variant_id=es_vars[0]["variant_id"], en_variant_id=en_v["variant_id"],
            target_kind=target_kind,
            n_components=len(pcs), n_products=len({p["product_id"] for p in pcs}),
            es_substance=dict(es_row), es_variant=dict(es_vars[0]),
            product_components=[dict(p) for p in pcs],
            evidence=r["evidence"], confidence=r["confidence"],
            csv_dups=r.get("_csv_dups", 1)))
        if verbose:
            print(f"  OK {r['es_name']} ({len(pcs)} 组件) {es_sid} -> {en_sid} [{target_kind}]")
    return dict(rows=rows, status_counts=status_counts, accepted=accepted,
                skipped=skipped, errors=errors)


def print_plan(p: dict) -> None:
    accepted = p["accepted"]
    print(f"CSV 行数: {len(p['rows'])}  mergeable 行: {p['status_counts'].get(PROCESS_STATUS, 0)}")
    print("状态分布: " + ", ".join(f"{k}={v}" for k, v in sorted(p["status_counts"].items())))
    print(f"可合并: {len(accepted)} 个 ES 成分 -> 英文成分")
    print(f"受影响产品(去重): {sum(a['n_products'] for a in accepted)}")
    print(f"将移动 product_component 行: {sum(a['n_components'] for a in accepted)}")
    print(f"将删除 variant: {len(accepted)}，删除 substance: {len(accepted)}")
    kinds = Counter(a["target_kind"] for a in accepted)
    if kinds:
        print(f"挂载方式: base={kinds.get('base', 0)}, salt匹配={kinds.get('salt', 0)}")
    if p["errors"]:
        print(f"\n!! CSV/DB 校验错误 {len(p['errors'])} 条（这些行不会被合并）:")
        for e in p["errors"][:20]:
            print(f"   {e['es_sid']} {e['es']} -> {e['en_sid']}: {e['reason']}")
    if p["skipped"]:
        by_reason: Counter = Counter()
        for s in p["skipped"]:
            key = re.sub(r"[\d:='\"]+", "N", s["reason"]).split("（")[0]
            by_reason[key] += 1
        print(f"\n跳过 {len(p['skipped'])} 行，原因分布:")
        for k, v in by_reason.most_common(12):
            print(f"   {v:>4}  {k}")
        print("   明细（前 15）:")
        for s in p["skipped"][:15]:
            print(f"   {s['es_sid']} {s['es']} -> {s['en_sid']}: {s['reason']}")
    if accepted:
        print("\n计划合并清单（按产品数排序）:")
        print(f"  {'产品':>5} {'组件':>5}  {'ES 成分':<36} {'西语名':<26} 英文目标")
        for a in sorted(accepted, key=lambda x: (-x["n_products"], x["es_sid"])):
            print(f"  {a['n_products']:>5} {a['n_components']:>5}  {a['es_sid']:<36}"
                  f" {a['es_name'][:24]:<26} {a['en_sid']} ({a['en_inn']})")


# ---------------------------------------------------------------------------
def apply(con, p: dict, db_path: Path, csv_path: Path, manifest_path: Path) -> int:
    accepted = p["accepted"]
    if not accepted:
        print("没有可合并的行（幂等或全部被跳过），未写库。")
        return 0
    manifest = {
        "tool": "etl/merge_es_substances.py",
        "db": str(db_path.resolve()),
        "csv": str(csv_path.resolve()),
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest()
        if csv_path.exists() else "",
        "created_at": utc_now(), "committed": False, "merges": [],
    }
    merged = 0
    try:
        con.execute("BEGIN IMMEDIATE")
        for a in accepted:
            rec = {
                "es_name": a["es_name"], "en_inn": a["en_inn"],
                "es_substance_id": a["es_sid"], "en_substance_id": a["en_sid"],
                "es_variant_id": a["es_variant_id"],
                "en_target_variant_id": a["en_variant_id"],
                "target_kind": a["target_kind"],
                "es_substance_row": a["es_substance"],
                "es_variant_row": a["es_variant"],
                "product_components": a["product_components"],
                "n_products": a["n_products"],
                "evidence": a["evidence"], "confidence": a["confidence"],
            }
            con.execute("UPDATE product_component SET variant_id=? WHERE variant_id=?",
                        (a["en_variant_id"], a["es_variant_id"]))
            con.execute("DELETE FROM variant WHERE variant_id=?", (a["es_variant_id"],))
            cur = con.execute("DELETE FROM substance WHERE substance_id=?", (a["es_sid"],))
            if cur.rowcount != 1:
                raise RuntimeError(f"删除 substance {a['es_sid']} 影响 {cur.rowcount} 行，中止")
            manifest["merges"].append(rec)
            merged += 1
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        con.commit()
        manifest["committed"] = True
        manifest["committed_at"] = utc_now()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    except Exception:
        con.rollback()
        print("!! 写库失败，已回滚事务", file=sys.stderr)
        raise
    print(f"已合并 {merged} 个 ES 成分；撤销清单: {manifest_path}")
    return merged


def rollback(con, manifest_path: Path) -> None:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not data.get("committed"):
        raise SystemExit(f"清单 {manifest_path} 未标记 committed，拒绝回滚")
    if data.get("rolled_back_at"):
        print(f"清单已于 {data['rolled_back_at']} 回滚过，继续执行幂等回填")
    restored = 0
    conflicts: list[str] = []
    con.execute("BEGIN IMMEDIATE")
    try:
        for rec in reversed(data["merges"]):
            es_sid = rec["es_substance_id"]
            es_vid = rec["es_variant_id"]
            en_vid = rec["en_target_variant_id"]
            sub = rec["es_substance_row"]
            var = rec["es_variant_row"]
            if not con.execute("SELECT 1 FROM substance WHERE substance_id=?",
                               (rec["en_substance_id"],)).fetchone():
                raise SystemExit(f"英文目标 {rec['en_substance_id']} 已不存在，拒绝回滚")
            if not con.execute("SELECT 1 FROM variant WHERE variant_id=?", (en_vid,)).fetchone():
                raise SystemExit(f"英文目标 variant {en_vid} 已不存在，拒绝回滚")
            con.execute(
                "INSERT OR IGNORE INTO substance (substance_id, inn_en, inn_zh, atc, atc_name,"
                " drug_class, ddd_value, ddd_unit, ddd_route) VALUES (?,?,?,?,?,?,?,?,?)",
                (sub["substance_id"], sub["inn_en"], sub["inn_zh"], sub["atc"],
                 sub["atc_name"], sub["drug_class"], sub["ddd_value"], sub["ddd_unit"],
                 sub["ddd_route"]))
            con.execute(
                "INSERT OR IGNORE INTO variant (variant_id, substance_id, salt, hydrate, ester,"
                " base_fraction, interchange, interchange_note) VALUES (?,?,?,?,?,?,?,?)",
                (var["variant_id"], var["substance_id"], var["salt"], var["hydrate"],
                 var["ester"], var["base_fraction"], var["interchange"],
                 var["interchange_note"]))
            for pc in rec["product_components"]:
                cur = con.execute(
                    "UPDATE product_component SET variant_id=?"
                    " WHERE product_id=? AND ord=? AND variant_id=?",
                    (es_vid, pc["product_id"], pc["ord"], en_vid))
                if cur.rowcount == 0:
                    still = con.execute(
                        "SELECT variant_id FROM product_component WHERE product_id=? AND ord=?",
                        (pc["product_id"], pc["ord"])).fetchone()
                    if not still:
                        conflicts.append(f"组件已不存在: {rec['es_name']} "
                                         f"{pc['product_id']}#{pc['ord']}")
                    elif still["variant_id"] != es_vid:
                        conflicts.append(f"组件指向已变化: {rec['es_name']} "
                                         f"{pc['product_id']}#{pc['ord']} -> {still['variant_id']}")
            restored += 1
        data["rolled_back_at"] = utc_now()
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        con.commit()
    except Exception:
        con.rollback()
        raise
    print(f"已回滚 {restored} 个合并（{manifest_path.name}）")
    if conflicts:
        print(f"!! {len(conflicts)} 个组件未能精确回挂（需人工检查）:")
        for c in conflicts[:20]:
            print("   " + c)
        raise SystemExit(2)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="把 ES/MX 专属西语成分（mx-es-* 等）合并到已有英文 INN 成分（默认 dry-run）。")
    ap.add_argument("--csv", default=str(CSV_DEFAULT), help="覆盖映射 CSV")
    ap.add_argument("--db", default=str(DB_DEFAULT), help="SQLite 数据库")
    ap.add_argument("--apply", action="store_true", help="真正写库（事务 + 撤销清单）")
    ap.add_argument("--dry-run", action="store_true", help="只出计划（默认行为）")
    ap.add_argument("--rollback", nargs="?", const="latest", default=None,
                    help="回滚：可给清单路径，缺省取 .tmp/es-map 最新清单")
    ap.add_argument("--manifest", default=None, help="--apply 撤销清单路径")
    ap.add_argument("--include-unprefixed", action="store_true",
                    help="同时处理非 mx-es- 前缀的 ES 独有西语 id（校验产品只在 ES/MX）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在: {db_path}")

    if args.rollback is not None:
        con = connect(db_path, readonly=False)
        try:
            if args.rollback == "latest":
                cands = sorted(MANIFEST_DIR.glob("merge_undo_*.json"),
                               key=lambda x: x.stat().st_mtime)
                if not cands:
                    raise SystemExit(f"{MANIFEST_DIR} 下没有 merge_undo_*.json")
                mp = cands[-1]
            else:
                mp = Path(args.rollback)
            print(f"回滚清单: {mp}")
            rollback(con, mp)
        finally:
            con.close()
        return

    csv_path = Path(args.csv)
    rows, csv_errors = load_csv(csv_path)
    for e in csv_errors:
        print("!! CSV 错误: " + e, file=sys.stderr)
    if not rows:
        raise SystemExit(1)

    readonly = not args.apply
    con = connect(db_path, readonly=readonly)
    try:
        p = plan(con, rows, include_unprefixed=args.include_unprefixed, verbose=args.verbose)
        print(f"DB: {db_path}  ({'只读' if readonly else '读写'})")
        print(f"CSV: {csv_path}")
        print()
        print_plan(p)
        if args.apply:
            if csv_errors:
                print("\n!! 存在 CSV 结构错误，拒绝 apply。", file=sys.stderr)
                raise SystemExit(1)
            if p["errors"]:
                print("\n!! 存在行级校验错误，拒绝 apply。", file=sys.stderr)
                raise SystemExit(1)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            manifest_path = Path(args.manifest) if args.manifest else (
                MANIFEST_DIR / f"merge_undo_{stamp}.json")
            print()
            apply(con, p, db_path, csv_path, manifest_path)
        else:
            print("\n(dry-run，未写库。加 --apply 执行)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
