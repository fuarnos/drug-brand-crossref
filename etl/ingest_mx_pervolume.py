# -*- coding: utf-8 -*-
"""MX per_volume 浓度挽回（默认 dry-run）。

背景
----
上轮 `etl/ingest_mx_ccby.py` 的 963 条浓度回填里，357 条被判 FAIL、19 条 UNCERTAIN：
其中 **125 条**原文其实给了明确基数（每 mL / 每 5 mL / 每 100 mL / 每瓶 / 每安瓿 / 每克），
只是 ETL 只取「第一个浓度」、没把基数写进 `product_component.per_volume_*`。
本脚本读 `data/mx_pervolume_candidates.csv`（由 `.tmp/mx-pervolume/extract.py` 生成），
只把这些**能明确折算**的写进 `strength_value/unit + per_volume_value/unit`。

规则（保守）
-----------
1. 只处理 `write_ok=yes` 且 confidence ∈ {high, medium} 的候选（extract 已排除：
   固体产品套液体原文、多个互相矛盾的折算值、low confidence）。
2. 只写 `product_component.ord=0 且 strength_value IS NULL 且 per_volume_value IS NULL` 的行
   （幂等；已有浓度的产品一律不动）。
3. 写入：`strength_value/strength_unit`（原文数值）+ `per_volume_value/per_volume_unit`
   （基数，如 5 ml / 100 ml / 3 ml / 100 g；`per_volume_unit=g` 仅外用）。
4. 来源：写 `corroboration`（source_type='provincial_list'，url=CC-BY 数据集资源页，
   verified_by=本脚本，note 带原文片段），并在报告里按 CC-BY-4.0 署名。
5. `--apply` 默认拒绝写 `data/drugs.db`（本任务要求只在 `.tmp/mx-pervolume/` 副本验证）。

用法：
    python etl/ingest_mx_pervolume.py                          # dry-run（只读）
    python etl/ingest_mx_pervolume.py --apply --db .tmp/mx-pervolume/drugs-test.db
    python etl/ingest_mx_pervolume.py --rollback --db .tmp/mx-pervolume/drugs-test.db
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
CAND = ROOT / "data" / "mx_pervolume_candidates.csv"
EVID = ROOT / ".tmp" / "mx-pervolume"
APPLIED = EVID / "applied_mx_pervolume.json"
TODAY = date.today().isoformat()
SOURCE_ID = "mx_ccby_pervolume"
ALLOWED_CONF = {"high", "medium"}


def connect(db_path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = "file:" + str(db_path.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=60)
    else:
        con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    return con


def load_candidates() -> list[dict]:
    if not CAND.exists():
        raise SystemExit(f"候选不存在：{CAND.relative_to(ROOT)}（先生成 data/mx_pervolume_candidates.csv）")
    rows = list(csv.DictReader(CAND.open(encoding="utf-8-sig")))
    out = []
    for r in rows:
        if r.get("write_ok") != "yes" or r.get("confidence") not in ALLOWED_CONF:
            continue
        try:
            sv = float(r["strength_value"])
            pv = float(r["per_volume_value"])
        except (KeyError, ValueError):
            continue
        if not (sv > 0 and pv > 0):
            continue
        out.append({**r, "sv": sv, "pv": pv})
    return out


def check_state(con: sqlite3.Connection, cands: list[dict]) -> tuple[list[dict], dict]:
    """只保留库里仍为空的行；统计不可写原因。"""
    ok, stats = [], Counter()
    for c in cands:
        row = con.execute(
            "SELECT strength_value, per_volume_value, pc.ord FROM product_component pc"
            " WHERE pc.product_id=? AND pc.ord=0", (c["product_id"],)).fetchone()
        if row is None:
            stats["no_component"] += 1
            continue
        if row["strength_value"] is not None:
            stats["already_strength"] += 1
            continue
        if row["per_volume_value"] is not None:
            stats["already_per_volume"] += 1
            continue
        ok.append(c)
    return ok, dict(stats)


def coverage(con: sqlite3.Connection, n_fill: int) -> dict:
    def one() -> tuple[int, int, int]:
        total = con.execute("SELECT COUNT(*) FROM product WHERE country='MX'").fetchone()[0]
        with_s = con.execute("""SELECT COUNT(DISTINCT p.product_id) FROM product p
            JOIN product_component pc ON pc.product_id=p.product_id
            WHERE p.country='MX' AND pc.strength_value IS NOT NULL""").fetchone()[0]
        with_pv = con.execute("""SELECT COUNT(DISTINCT p.product_id) FROM product p
            JOIN product_component pc ON pc.product_id=p.product_id
            WHERE p.country='MX' AND pc.per_volume_value IS NOT NULL""").fetchone()[0]
        return total, with_s, with_pv
    total, ws, wpv = one()
    return {
        "mx_products_total": total,
        "products_with_strength_before": ws,
        "products_with_strength_after": ws + n_fill,
        "coverage_before": round(100.0 * ws / max(1, total), 1),
        "coverage_after": round(100.0 * (ws + n_fill) / max(1, total), 1),
        "products_with_per_volume_before": wpv,
        "products_with_per_volume_after": wpv + n_fill,
    }


def dryrun(cands: list[dict], stats: dict, cover: dict) -> None:
    EVID.mkdir(parents=True, exist_ok=True)
    result = {
        "generated_at": TODAY, "mode": "dry-run",
        "candidate_rows": len(cands), "writable": len(cands),
        "state_skips": stats, "coverage": cover,
        "by_basis": dict(Counter(c["basis_kind"] for c in cands)),
        "by_form": dict(Counter(c["form_base"] for c in cands)),
        "by_confidence": dict(Counter(c["confidence"] for c in cands)),
        "samples": cands[:20], "all": cands,
    }
    (EVID / "pervolume_dryrun.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# MX per_volume 浓度挽回 dry-run（etl/ingest_mx_pervolume.py）", "",
             f"生成时间：{TODAY}  候选：{len(cands)} 条可写", "",
             "## 覆盖率", 
             f"- MX 产品：{cover['products_with_strength_before']:,}/{cover['mx_products_total']:,}"
             f" = {cover['coverage_before']}% → {cover['products_with_strength_after']:,}"
             f" = {cover['coverage_after']}%",
             f"- 有 per_volume 的 MX 产品：{cover['products_with_per_volume_before']:,} → "
             f"{cover['products_with_per_volume_after']:,}", "",
             "## 按基数类型", ]
    for k, v in result["by_basis"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## 抽样 20 条", "",
              "| # | product_id | 剂型 | 原文数值 | 折算 | 基数类型 | 置信 |",
              "|---:|---|---|---|---|---|---|"]
    for i, c in enumerate(cands[:20], 1):
        lines.append(f"| {i} | {c['product_id']} | {c['form_base']} | {c['fill_value']}"
                     f"{c['fill_unit']} | {c['strength_value']} {c['strength_unit']}"
                     f"/{c['per_volume_value']} {c['per_volume_unit']} | {c['basis_kind']} |"
                     f" {c['confidence']} |")
    (EVID / "pervolume_dryrun.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"dry-run 报告：{(EVID / 'pervolume_dryrun.json').relative_to(ROOT)}")
    print(f"             {(EVID / 'pervolume_dryrun.txt').relative_to(ROOT)}")


def apply(con: sqlite3.Connection, cands: list[dict]) -> dict:
    written = Counter()
    applied: list[dict] = []
    try:
        # 复用上轮已登记的 ccby source 行；若不存在则补一条（幂等）
        for key, label in (("inprfm", "INPRFM — Adquisición de medicamentos"),
                           ("hgmgg", "HGMGG — Medicamentos adquiridos"),
                           ("iner", "INER — Entrada de medicamentos"),
                           ("semar", "SEMAR — Adquisición de insumos")):
            con.execute(
                "INSERT OR IGNORE INTO source (source_id, name, url, license, license_url,"
                " retrieved_at, notes) VALUES (?,?,?,?,?,?,?)",
                (f"{key}_ccby", label,
                 "https://datos.gob.mx/api/3/action/package_search?q=medicamentos",
                 "CC-BY-4.0", "https://creativecommons.org/licenses/by/4.0/", TODAY,
                 "datos.gob.mx 采购明细（CC BY 4.0），per_volume 折算自原文。"))
        for c in cands:
            cur = con.execute(
                "UPDATE product_component SET strength_value=?, strength_unit=?,"
                " per_volume_value=?, per_volume_unit=?"
                " WHERE product_id=? AND ord=0 AND strength_value IS NULL"
                " AND per_volume_value IS NULL",
                (c["sv"], c["strength_unit"], c["pv"], c["per_volume_unit"], c["product_id"]))
            if cur.rowcount != 1:
                written["skip_race"] += 1
                continue
            written["components"] += 1
            ds = (c.get("evidence_datasets") or "").split(",")[0].strip() or "ccby"
            url = c.get("evidence_url") or ("ccby:%s" % ds)
            note = ("per_volume 回填自 mx_ccby:%s；原文 %s %s / %s %s（%s）" % (
                c.get("evidence_datasets") or ds, c["strength_value"], c["strength_unit"],
                c["per_volume_value"], c["per_volume_unit"], c["basis_kind"]))
            con.execute(
                "INSERT OR IGNORE INTO corroboration (product_id, source_type, url,"
                " retrieved_at, verified_by, note) VALUES (?,?,?,?,?,?)",
                (c["product_id"], "provincial_list", url, TODAY,
                 "etl/ingest_mx_pervolume.py", note))
            applied.append({"product_id": c["product_id"], "strength_value": c["sv"],
                            "strength_unit": c["strength_unit"],
                            "per_volume_value": c["pv"],
                            "per_volume_unit": c["per_volume_unit"]})
        con.execute(
            "INSERT OR REPLACE INTO ingest_run (run_id, source_id, started_at, finished_at,"
            " rows_in, rows_kept, rows_rejected, status, note) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{SOURCE_ID}-{TODAY}", SOURCE_ID, TODAY, TODAY,
             len(cands), written["components"], written["skip_race"], "ok",
             json.dumps({"written": dict(written)}, ensure_ascii=False)))
        con.commit()
        EVID.mkdir(parents=True, exist_ok=True)
        # 幂等：重跑写 0 时不清空上一轮清单
        prev = []
        if APPLIED.exists():
            try:
                prev = json.loads(APPLIED.read_text(encoding="utf-8")).get("entries") or []
            except json.JSONDecodeError:
                prev = []
        merged = {e["product_id"]: e for e in prev + applied}
        APPLIED.write_text(json.dumps(
            {"applied_at": TODAY, "source_id": SOURCE_ID, "count": len(merged),
             "entries": list(merged.values())}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        con.rollback()
        raise
    return dict(written)


def rollback(con: sqlite3.Connection) -> dict:
    out = Counter()
    if not APPLIED.exists():
        raise SystemExit(f"找不到 {APPLIED.relative_to(ROOT)}：拒绝回滚（避免误伤已有浓度）。")
    payload = json.loads(APPLIED.read_text(encoding="utf-8"))
    entries = payload.get("entries") or []
    try:
        for e in entries:
            cur = con.execute(
                "UPDATE product_component SET strength_value=NULL, strength_unit=NULL,"
                " per_volume_value=NULL, per_volume_unit=NULL"
                " WHERE product_id=? AND ord=0 AND strength_value=? AND per_volume_value=?",
                (e["product_id"], e["strength_value"], e["per_volume_value"]))
            if cur.rowcount == 1:
                out["components"] += 1
            con.execute("DELETE FROM corroboration WHERE product_id=? AND verified_by=?",
                        (e["product_id"], "etl/ingest_mx_pervolume.py"))
        con.execute("DELETE FROM ingest_run WHERE run_id=?", (f"{SOURCE_ID}-{TODAY}",))
        con.commit()
        APPLIED.write_text(json.dumps(
            {"applied_at": payload.get("applied_at"), "source_id": SOURCE_ID,
             "count": 0, "entries": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        con.rollback()
        raise
    out["listed"] = len(entries)
    return dict(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="MX per_volume 浓度挽回（默认 dry-run）")
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--allow-real", action="store_true",
                    help="允许 --apply/--rollback 写 data/drugs.db（默认禁止；正式 apply 由 Lead 决定）")
    args = ap.parse_args()
    if sum([args.apply, args.dry_run, args.rollback]) > 1:
        ap.error("--apply / --dry-run / --rollback 互斥")
    real = (ROOT / "data" / "drugs.db").resolve()
    if (args.apply or args.rollback) and args.db.resolve() == real and not args.allow_real:
        raise SystemExit("拒绝写 data/drugs.db：本任务要求只在 .tmp/mx-pervolume/ 副本验证；"
                         "若 Lead 批准正式 apply，再加 --allow-real（先备份库）。")

    cands_all = load_candidates()
    con = connect(args.db, readonly=not (args.apply or args.rollback))
    if args.rollback:
        out = rollback(con)
        print(f"已回滚：{out.get('components', 0):,} 个组件（清单 {out.get('listed', 0):,} 条）")
        con.close()
        return 0
    cands, skipped = check_state(con, cands_all)
    cover = coverage(con, len(cands))
    print("=== MX per_volume 挽回 [%s] ===" % ("apply" if args.apply else "dry-run"))
    print(f"候选（write_ok=yes, high/medium）：{len(cands_all):,}"
          f"；库里可写：{len(cands):,}；跳过：{skipped}")
    print("按基数：", dict(Counter(c["basis_kind"] for c in cands)))
    print("按剂型：", dict(Counter(c["form_base"] for c in cands)))
    print(f"MX 有浓度产品：{cover['products_with_strength_before']:,}/{cover['mx_products_total']:,}"
          f" = {cover['coverage_before']}% → {cover['products_with_strength_after']:,}"
          f" = {cover['coverage_after']}%")
    print(f"MX 有 per_volume 产品：{cover['products_with_per_volume_before']:,} →"
          f" {cover['products_with_per_volume_after']:,}")
    print(f"抽样 {min(args.sample, len(cands))} 条：")
    for c in cands[: args.sample]:
        print(f"  {c['product_id']:<14} {c['form_base']:<9} {c['strength_value']:>8} "
              f"{c['strength_unit']:<4}/{c['per_volume_value']:>5} {c['per_volume_unit']:<2} "
              f"[{c['basis_kind']}/{c['confidence']}] {c['inn'][:26]}")
    if args.apply:
        written = apply(con, cands)
        print(f"已写库：{written.get('components', 0):,} 个组件（事务提交）")
    else:
        dryrun(cands, skipped, cover)
        print("（未写库；正式执行用 --apply --db <副本>）")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
