"""P1 自动化：检测并合并「同一成分被拆成两个 id」的重复。

判据（不靠人工列表）：
  1. ATC 编码前 5 位相同，且英文名编辑距离 <= 2  -> 候选
  2. 英文名归一化后完全相同（只差大小写/空格/标点） -> 直接合并
  3. 中文名相同 -> 候选

两种用法
--------
A. 全库扫描（原有行为，保持不变）：
    python etl/auto_merge_substances.py                  # 只出报告（reports/substance_duplicates.csv）
    python etl/auto_merge_substances.py --apply          # 执行合并（保留产品多的 id）
B. 指定 pair 列表（task-52：batch A 的 25 对 cn-* 同名重复，可在 DB 副本上验证）：
    python etl/auto_merge_substances.py --db .tmp/cross-market/drugs-test.db \
        --pairs .tmp/cross-market/batch_a_30.csv --dry-run
    python etl/auto_merge_substances.py --db ... --pairs ... --apply \
        --manifest .tmp/cross-market/auto_merge_manifest.json
    python etl/auto_merge_substances.py --db ... --rollback .tmp/cross-market/auto_merge_manifest.json

安全约束
--------
- **只删 cn-* 成分**（与 merge_cn_substances.py 同底线：永不删英文成分）；
- 目标必须是已存在的 substance；`--pairs` 模式默认要求 dup 和 canonical 都以 `cn-` 开头
  （`--allow-non-cn` 可放开，供未来英文重复使用）；
- 合并 = 把 dup 的所有 variant 改挂到 canonical，再删 dup substance；product_component 不动；
- `--apply` 事务化，任何一行校验/删除异常整体回滚；先写撤销清单（含 substance 原始行+variant ids）。

本文件 task-52 新增 `--db/--pairs/--dry-run/--apply/--rollback/--manifest/--report`，
原有「全库扫描 + --apply」用法与默认输出路径不变。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
REPORT = ROOT / "reports" / "substance_duplicates.csv"
EVID = ROOT / ".tmp" / "auto-merge"
CSV_COLS = ["canonical", "dup_id", "dup_name", "products"]


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def norm(s: str) -> str:
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


def connect(db_path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = "file:" + str(db_path.resolve()).replace("\\", "/").replace(" ", "%20") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=60)
    else:
        con = sqlite3.connect(db_path, timeout=120)
    con.row_factory = sqlite3.Row
    return con


def substance_columns(con: sqlite3.Connection) -> list[str]:
    return [r[1] for r in con.execute("PRAGMA table_info(substance)")]


def load_pairs_csv(path: Path) -> list[tuple[str, str]]:
    """读取 pair 列表；兼容 batch_a_30.csv（route 列）与候选 CSV（source_id/target_id）。"""
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    pairs: list[tuple[str, str]] = []
    for r in rows:
        src = (r.get("source_id") or r.get("dup_id") or "").strip()
        tgt = (r.get("target_id") or r.get("canonical") or "").strip()
        route = (r.get("route") or r.get("candidate_type") or "").strip()
        status = (r.get("status") or "").strip()
        if route and route not in ("auto_merge", "duplicate_merge"):
            continue
        if status and status != "mergeable":
            continue
        if src and tgt and src != tgt:
            pairs.append((src, tgt))
    return pairs


def full_scan(con: sqlite3.Connection) -> list[dict]:
    """全库扫描：同 ATC-4 且英文名/中文名完全相同的重复组（原有逻辑）。"""
    rows = con.execute(
        """SELECT s.substance_id, s.inn_en, s.inn_zh, s.atc,
                  (SELECT COUNT(*) FROM variant v JOIN product_component pc
                     ON pc.variant_id = v.variant_id
                    WHERE v.substance_id = s.substance_id) AS n
           FROM substance s""").fetchall()
    print(f"成分 {len(rows)} 个")
    by_atc: dict[str, list] = defaultdict(list)
    for sid, en, zh, atc, n in rows:
        if atc and len(atc) >= 5:
            by_atc[atc[:5]].append((sid, en, zh, n))
    pairs: list[tuple] = []
    for atc, group in by_atc.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                na, nb = norm(a[1]), norm(b[1])
                if not na or not nb:
                    continue
                if na == nb or (a[2] and a[2] == b[2]):
                    pairs.append((atc, a, b))
    print(f"同 ATC-4 下的疑似重复: {len(pairs)} 对")
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for _atc, a, b in pairs:
        union(a[0], b[0])
    groups: dict[str, list] = defaultdict(list)
    for sid, en, zh, _atc, n in rows:
        if sid in parent:
            groups[find(sid)].append((sid, en, zh, n))
    multi = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"应合并成一组: {len(multi)} 组，涉及 {sum(len(v) for v in multi.values())} 个 id")
    plan: list[dict] = []
    for _root, members in sorted(multi.items(), key=lambda kv: -sum(m[3] for m in kv[1])):
        members.sort(key=lambda m: -m[3])
        canon = members[0]
        for m in members[1:]:
            plan.append({"dup_id": m[0], "canon": canon[0], "canon_name": canon[1],
                         "dup_name": m[1], "n_products": m[3]})
    return plan


def build_plan(con: sqlite3.Connection, pairs: list[tuple[str, str]],
               require_cn: bool = True) -> tuple[list[dict], list[str]]:
    cols = substance_columns(con)
    plan: list[dict] = []
    errors: list[str] = []
    for dup, canon in pairs:
        if require_cn and not (dup.startswith("cn-") and canon.startswith("cn-")):
            errors.append(f"{dup} → {canon}: 非 cn-* 对（--pairs 模式要求 cn- 前缀）")
            continue
        d = con.execute("SELECT * FROM substance WHERE substance_id=?", (dup,)).fetchone()
        c = con.execute("SELECT * FROM substance WHERE substance_id=?", (canon,)).fetchone()
        if not d:
            errors.append(f"{dup}: dup substance 不存在")
            continue
        if not c:
            errors.append(f"{canon}: canonical substance 不存在")
            continue
        vids = [r[0] for r in con.execute(
            "SELECT variant_id FROM variant WHERE substance_id=?", (dup,))]
        ncomp = con.execute(
            "SELECT COUNT(*) FROM product_component WHERE variant_id IN "
            "(SELECT variant_id FROM variant WHERE substance_id=?)", (dup,)).fetchone()[0]
        plan.append({"dup_id": dup, "canon": canon, "variant_ids": vids,
                     "n_components": ncomp,
                     "substance_row": {k: d[k] for k in cols}})
    return plan, errors


def write_report(plan: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLS)
        for p in plan:
            w.writerow([p["canon"], p["dup_id"], p.get("dup_name", ""),
                        p.get("n_components", p.get("n_products", 0))])
    print(f"报告: {path}")


def apply_plan(con: sqlite3.Connection, plan: list[dict], db_path: Path,
               manifest_path: Path) -> int:
    if not plan:
        print("没有可合并项，未写库。")
        return 0
    manifest = {"tool": "etl/auto_merge_substances.py", "db": str(db_path.resolve()),
                "created_at": utc_now(), "committed": False, "merges": []}
    merged = 0
    con.execute("BEGIN IMMEDIATE")
    try:
        for p in plan:
            for vid in p["variant_ids"]:
                con.execute("UPDATE variant SET substance_id=? WHERE variant_id=?",
                            (p["canon"], vid))
            cur = con.execute("DELETE FROM substance WHERE substance_id=?", (p["dup_id"],))
            if cur.rowcount != 1:
                raise RuntimeError("删除 %s 影响 %d 行，中止" % (p["dup_id"], cur.rowcount))
            manifest["merges"].append(p)
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
        raise
    print(f"已合并 {merged} 个重复 id；撤销清单: {manifest_path}")
    return merged


def rollback(con: sqlite3.Connection, manifest_path: Path) -> int:
    if not manifest_path.exists():
        raise SystemExit(f"找不到撤销清单: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not data.get("committed"):
        raise SystemExit("清单未标记 committed，拒绝回滚")
    cols = substance_columns(con)
    restored = 0
    con.execute("BEGIN IMMEDIATE")
    try:
        for rec in reversed(data["merges"]):
            row = rec["substance_row"]
            con.execute(
                "INSERT OR IGNORE INTO substance (%s) VALUES (%s)" % (
                    ",".join(cols), ",".join("?" * len(cols))),
                [row.get(c) for c in cols])
            for vid in rec["variant_ids"]:
                con.execute("UPDATE variant SET substance_id=? WHERE variant_id=?",
                            (rec["dup_id"], vid))
            restored += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    data["rolled_back_at"] = utc_now()
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    print(f"已回滚 {restored} 个重复合并（substance 行恢复，variant 改回）")
    return restored


def main() -> int:
    ap = argparse.ArgumentParser(description="合并「同一成分被拆成两个 id」的重复")
    ap.add_argument("--db", type=Path, default=DB, help="SQLite 数据库（默认 data/drugs.db）")
    ap.add_argument("--pairs", type=Path, default=None,
                    help="pair 列表 CSV（source_id/target_id 或 route=auto_merge 的 batch CSV）")
    ap.add_argument("--dry-run", action="store_true", help="只出计划（默认行为）")
    ap.add_argument("--apply", action="store_true", help="执行合并（事务 + 撤销清单）")
    ap.add_argument("--rollback", nargs="?", const="latest", default=None,
                    help="按撤销清单回滚（可给路径；默认 --manifest）")
    ap.add_argument("--manifest", type=Path, default=None, help="撤销清单路径")
    ap.add_argument("--report", type=Path, default=None,
                    help="dry-run 报告 CSV（全库扫描默认 reports/substance_duplicates.csv）")
    ap.add_argument("--allow-non-cn", action="store_true",
                    help="--pairs 模式允许非 cn-* 的 pair（默认只允许 cn-→cn-）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if sum([bool(args.apply), bool(args.rollback), bool(args.dry_run)]) > 1:
        ap.error("--apply / --rollback / --dry-run 互斥")

    legacy = args.pairs is None
    if args.rollback:
        manifest = Path(args.rollback) if args.rollback != "latest" else (
            args.manifest or EVID / "auto_merge_manifest.json")
        con = connect(args.db, readonly=False)
        n = rollback(con, manifest)
        con.close()
        return 0

    con = connect(args.db, readonly=not args.apply)
    if legacy:
        plan = full_scan(con)
        report_path = args.report or REPORT
        write_report(plan, report_path)
        if args.verbose:
            for p in plan[:20]:
                print("  %-20s → %-20s（%d 组件）" % (
                    p["dup_id"], p["canon"], p["n_components"]))
    else:
        pairs = load_pairs_csv(args.pairs)
        print(f"pair 列表: {len(pairs)} 对（{args.pairs}）")
        plan, errors = build_plan(con, pairs, require_cn=not args.allow_non_cn)
        for e in errors:
            print("  reject:", e)
        print(f"可合并: {len(plan)} 对；拒绝: {len(errors)}")
        for p in plan[:10]:
            print("  %-22s → %-22s variants=%d components=%d" % (
                p["dup_id"], p["canon"], len(p["variant_ids"]), p["n_components"]))
        if args.report:
            write_report(plan, args.report)

    if not args.apply:
        print("（dry-run，未写库；加 --apply 执行）")
        con.close()
        return 0
    if not plan:
        con.close()
        return 0
    manifest = args.manifest or EVID / "auto_merge_manifest.json"
    merged = apply_plan(con, plan, args.db, manifest)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
