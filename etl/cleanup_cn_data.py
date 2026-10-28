# -*- coding: utf-8 -*-
"""CN（中国）数据清洗批次 — form_base / 规格 / 重复 / 批文格式（只限 DB 副本）。

背景：reports/cn-data-intuition-audit.md P1。真实库写入需窗口 + `--allow-real`。
本脚本只做「规则化清洗 + 可回滚」：
  1) form_base：67 类长尾 → canonical 枚举（tablet/capsule/injection/topical/powder/
     liquid/suppository/inhalation/pill/other/unknown）；原始剂型文本仍在 dosage_form，
     检测/试剂类 → other + note 标记 `cn-cleanup:diagnostic_reagent`。
  2) 规格：异常 30 行（strength_value >100000 或 <=0）→ 置 NULL + note 标记（不猜值）；
     5,230 个无规格产品 → note 标记 `cn-cleanup:no_strength`（不新增值）。
  3) 重复：精确重复（批文+MAH+剂型+释放+包装+成分规格签名）756 组/2,042 行 →
     保留最小 product_id，其余删除前快照到 `cleanup_cn_deleted_product`（可回滚）；
     「同批文+商品名+规格」近重复 → 写入 `cleanup_cn_dup_review` 标记待复核，不删。
  4) 批文：去「(参照)」后缀、清空白/全角；993 行进口格式（H/HC/S/J…）保留原格式并标
     `approval_origin=import`；可判定为国产缺前缀的中国 MAH 行补「国药准字」前缀
     （保守启发式，写入 note 供复核）；原值写 note `approval_raw=...`。仅改 approval_id。

回滚：`--rollback` 用 journal 恢复字段、用快照恢复被删产品，并清 review 表。
CLI：
    python etl/cleanup_cn_data.py --dry-run
    python etl/cleanup_cn_data.py --apply --db .tmp/cn-cleanup/test.db
    python etl/cleanup_cn_data.py --rollback --db .tmp/cn-cleanup/test.db
    python etl/cleanup_cn_data.py --apply --db data/drugs.db --allow-real
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "drugs.db"
WORK = ROOT / ".tmp" / "cn-cleanup"
DEFAULT_RUN_ID = "cn-cleanup-v1"

# canonical 剂型（audit 的 11 值 + build.py LABEL_I18N 支持的 pellet/stick/kit/gas）
CANON_FORMS = {"tablet", "capsule", "injection", "topical", "powder", "liquid",
               "suppository", "inhalation", "pill", "other", "unknown",
               "pellet", "stick", "kit", "gas"}

FORM_MAP = {
    "灌肠剂": "liquid", "体外诊断试剂": "other", "缓释制剂": "unknown",
    "冻干粉针剂": "injection", "滴剂": "liquid", "口服乳剂": "liquid",
    "眼膏剂": "topical", "鼻用制剂": "topical", "粉雾剂": "inhalation",
    "耳用制剂": "topical", "冻干粉": "powder", "放免诊断试剂盒": "other",
    "涂剂": "topical", "植入剂": "other", "冻干制剂": "injection",
    "锭剂": "tablet", "冻干粉剂": "injection", "橡胶膏剂": "topical",
    "诊断试剂盒": "other", "含漱剂": "liquid", "乳胶剂": "topical",
    "控释制剂": "unknown", "外用冻干制剂": "topical", "诊断试剂": "other",
    "皮肤点刺试剂": "other", "糊剂": "topical", "咀嚼胶": "other",
    "冻干粉末": "injection", "醑剂": "liquid", "粉剂": "powder",
    "放射性密封源": "other", "其他:制剂(非中国药典剂型 冻干粉剂)": "unknown",
    "无菌冻干粉": "injection", "抗体诊断试剂盒": "other",
    "外用粉末剂": "powder", "其他:制剂(非中国药典剂型冻干粉剂)": "unknown",
    "-": "unknown", "硬膏剂": "topical", "火棉胶剂": "topical",
    "漱液剂": "liquid", "海绵剂": "topical", "泡沫剂": "topical",
    "宫内释放系统": "other", "合剂": "liquid", "体外诊断制剂": "other",
    "乳剂": "liquid", "": "unknown", "热敷剂": "topical", "点刺液": "other",
    "液体剂": "liquid", "液体制剂": "liquid", "外用制剂(冻干)": "topical",
    "体外诊断试剂盒": "other", "/": "unknown", "靶向制剂": "other",
    "露剂": "liquid", "试剂盒": "other", "棒剂": "stick",
    "放射性密封籽源": "other", "宫内节育系统": "other", "外用制剂": "topical",
    "外用冻干剂": "topical", "制剂:密封源": "other", "冻干粉针": "injection",
    "冻干": "injection", "\\": "unknown", "----": "unknown",
}
DIAGNOSTIC_FORMS = {
    "体外诊断试剂", "放免诊断试剂盒", "诊断试剂盒", "诊断试剂", "皮肤点刺试剂",
    "抗体诊断试剂盒", "体外诊断制剂", "体外诊断试剂盒", "点刺液", "试剂盒",
}
MARK_FORM = "cn-cleanup:form_base"
MARK_DIAG = "cn-cleanup:diagnostic_reagent"
MARK_STRENGTH_BAD = "cn-cleanup:strength_anomaly"
MARK_NO_STRENGTH = "cn-cleanup:no_strength"
MARK_APPROVAL_RAW = "cn-cleanup:approval_raw"
MARK_APPROVAL_IMPORT = "cn-cleanup:approval_origin=import"
MARK_APPROVAL_PREFIX = "cn-cleanup:approval_prefix_added"
MARK_APPROVAL_MULTI = "cn-cleanup:approval_multi"
MARK_APPROVAL_MISSING = "cn-cleanup:approval_missing"

RE_APPROVAL_CODE = re.compile(r"(?:国药准字)?[A-Z]{1,3}\d{8}")
RE_BARE_CODE = re.compile(r"^(H|HC|S|J|B|Z)\d{8}$")
RE_GUOYAO = re.compile(r"^国药准字")
HAN = re.compile(r"[\u3400-\u9fff]")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def add_marker(note: str | None, marker: str) -> str:
    """幂等追加标记（不重复）。"""
    note = (note or "").strip()
    if marker in note:
        return note
    return (note + "; " + marker) if note else marker


# ---------------------------------------------------------------- DDL
DDL = """
CREATE TABLE IF NOT EXISTS cleanup_cn_journal (
    run_id     TEXT NOT NULL,
    step       TEXT NOT NULL,
    product_id TEXT NOT NULL,
    field      TEXT NOT NULL,
    old_value  TEXT,
    new_value  TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ccj_run ON cleanup_cn_journal (run_id, product_id);
CREATE TABLE IF NOT EXISTS cleanup_cn_deleted_product (
    run_id      TEXT NOT NULL,
    product_id  TEXT NOT NULL,
    keeper_id   TEXT,
    snapshot    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, product_id)
);
CREATE TABLE IF NOT EXISTS cleanup_cn_dup_review (
    run_id     TEXT NOT NULL,
    product_id TEXT NOT NULL,
    group_key  TEXT NOT NULL,
    reason     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, product_id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_value(raw: str):
    """journal 的 old_value 是 str(old)；数值/字符串/None 都尽量还原。"""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return raw


def _connect(db_path: Path, write: bool) -> sqlite3.Connection:
    if write:
        con = sqlite3.connect(db_path, timeout=180)
    else:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=180)
    con.row_factory = sqlite3.Row
    return con


def _guard_real(db_path: Path, allow_real: bool) -> None:
    if db_path.resolve() == DEFAULT_DB.resolve() and not allow_real:
        raise SystemExit(
            f"拒絕在真實庫 {db_path} 寫入清洗：本任務只允許 DB 副本。\n"
            "真實窗口執行時加 --allow-real（先備份；建議先跑 dry-run 核對）。")


# ---------------------------------------------------------------- 各步检测
def scan_form(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        """SELECT product_id, form_base, dosage_form FROM product
           WHERE country='CN' AND (form_base IS NULL
                 OR form_base NOT IN (%s))""" % ",".join("?" * len(CANON_FORMS)),
        tuple(sorted(CANON_FORMS))).fetchall()
    out = []
    for pid, fb, df in rows:
        key = (fb or "").strip()
        target = FORM_MAP.get(key, "unknown")
        out.append({"product_id": pid, "old": fb, "new": target,
                    "diagnostic": key in DIAGNOSTIC_FORMS, "dosage_form": df})
    return out


def scan_strength_bad(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        """SELECT pc.product_id, pc.ord, pc.strength_value, pc.strength_unit,
                  pc.per_volume_value, pc.per_volume_unit
           FROM product p JOIN product_component pc ON pc.product_id=p.product_id
           WHERE p.country='CN' AND pc.strength_value IS NOT NULL
             AND (pc.strength_value<=0 OR pc.strength_value>100000)""").fetchall()]


def scan_no_strength(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute(
        """SELECT p.product_id FROM product p WHERE p.country='CN' AND NOT EXISTS (
             SELECT 1 FROM product_component pc WHERE pc.product_id=p.product_id
               AND pc.strength_value IS NOT NULL)""").fetchall()]


def scan_approval(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        """SELECT product_id, approval_id, mah, note FROM product
           WHERE country='CN'""").fetchall()
    out = []
    for pid, appr, mah, note in rows:
        raw = appr if appr is not None else ""
        text = nfkc(str(raw)).strip()
        if not text:
            continue
        canzhao = bool(re.search(r"[（(]\s*参照\s*[)）]", text))
        base = re.sub(r"[（(]\s*参照\s*[)）]", "", text).strip()
        base = re.sub(r"\s+", "", base)
        kind = "guoyao"
        marker = ""
        if canzhao:
            marker = MARK_APPROVAL_RAW
            kind = "canzhao"
        if RE_GUOYAO.match(base):
            new = base
        elif RE_BARE_CODE.match(base):
            if HAN.search(mah or ""):
                new = "国药准字" + base
                marker = " ".join(x for x in (marker, MARK_APPROVAL_PREFIX) if x)
                kind = "bare_cn_mah"
            else:
                # 进口注册证号：格式不变，仅在 note 标 import（幂等：已标则跳过）
                if MARK_APPROVAL_IMPORT in (note or ""):
                    continue
                new = base
                marker = " ".join(x for x in (marker, MARK_APPROVAL_IMPORT) if x)
                kind = "imported"
        elif RE_APPROVAL_CODE.search(base) and len(RE_APPROVAL_CODE.findall(base)) > 1:
            codes = [c if c.startswith("国药准字") else "国药准字" + c
                     for c in RE_APPROVAL_CODE.findall(base)]
            new = " / ".join(dict.fromkeys(codes))
            marker = " ".join(x for x in (marker, MARK_APPROVAL_MULTI) if x)
            kind = "multi"
        else:
            new = base
            kind = "other"
        if new != (appr or "") or marker:
            out.append({"product_id": pid, "old": appr, "new": new,
                        "note_marker": marker, "kind": kind})
    return out


def scan_exact_dups(con: sqlite3.Connection) -> list[dict]:
    rows = [dict(r) for r in con.execute(
        """SELECT p.product_id, p.approval_id, p.mah, p.dosage_form, p.release, p.pack,
                  GROUP_CONCAT(IFNULL(pc.strength_value,'') || '/' ||
                               IFNULL(pc.strength_unit,''), '|' ORDER BY pc.ord) sig
           FROM product p LEFT JOIN product_component pc ON pc.product_id=p.product_id
           WHERE p.country='CN' GROUP BY p.product_id""").fetchall()]
    groups = defaultdict(list)
    for r in rows:
        groups[(r["approval_id"], r["mah"], r["dosage_form"], r["release"], r["pack"],
                r["sig"])].append(r["product_id"])
    dups = []
    for key, pids in groups.items():
        if len(pids) > 1:
            pids = sorted(pids)
            keeper = pids[0]
            for pid in pids[1:]:
                dups.append({"product_id": pid, "keeper_id": keeper,
                             "approval_id": key[0], "n": len(pids)})
    return dups


def scan_pending_review(con: sqlite3.Connection) -> list[dict]:
    """audit 口径：同批文+商品名 norm+成分规格（组件行计数）>1 组 → 组内产品待复核，不删。"""
    rows = con.execute(
        """SELECT p.approval_id, nk.norm, pc.strength_value, pc.strength_unit,
                  GROUP_CONCAT(DISTINCT p.product_id) pids, COUNT(*) c
           FROM product p
           JOIN product_component pc ON pc.product_id=p.product_id
           JOIN product_name pn ON pn.product_id=p.product_id
           JOIN name_key nk ON nk.key_id=pn.key_id
           WHERE p.country='CN' AND pn.name_type='trade'
           GROUP BY 1,2,3,4 HAVING c>1""").fetchall()
    out = []
    for r in rows:
        appr, tnorm, sv, su, pids, c = r
        group_key = f"{appr}|{tnorm}|{sv}|{su}"
        for pid in (pids or "").split(","):
            if pid:
                out.append({"product_id": pid, "group_key": group_key,
                            "reason": "same_approval_name_strength"})
    return out


# ---------------------------------------------------------------- dry-run
def cmd_dry_run(args: argparse.Namespace) -> int:
    con = _connect(args.db, write=False)
    try:
        forms = scan_form(con)
        bad = scan_strength_bad(con)
        nos = scan_no_strength(con)
        appr = scan_approval(con)
        dups = scan_exact_dups(con)
        pend = scan_pending_review(con)
    finally:
        con.close()
    kinds = Counter(a["kind"] for a in appr)
    summary = {
        "db": str(args.db), "run_id": args.run_id,
        "form_base": {"rows": len(forms), "distinct_old": len({f["old"] for f in forms}),
                       "diagnostic_rows": sum(1 for f in forms if f["diagnostic"]),
                       "mapping": {k: FORM_MAP.get(k, "unknown")
                                   for k in sorted({(f["old"] or "").strip()
                                                    for f in forms})}},
        "strength_anomaly": {"rows": len(bad),
                              "samples": [[b["strength_value"], b["strength_unit"],
                                           b["product_id"]] for b in bad[:8]]},
        "no_strength": {"products": len(nos)},
        "approval": {"rows": len(appr), "kinds": dict(kinds),
                      "canzhao": kinds.get("canzhao", 0),
                      "imported": kinds.get("imported", 0),
                      "bare_cn_mah": kinds.get("bare_cn_mah", 0),
                      "multi": kinds.get("multi", 0),
                      "missing": kinds.get("missing", 0),
                      "samples": appr[:10]},
        "dup_exact": {"groups": len({d["keeper_id"] for d in dups}),
                       "delete_rows": len(dups),
                       "top": sorted(([d["approval_id"], d["n"]] for d in dups),
                                     key=lambda x: -x[1])[:8]},
        "dup_review": {"rows": len(pend),
                        "groups": len({p["group_key"] for p in pend})},
    }
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "dryrun.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    print("=== CN cleanup dry-run ===")
    print(f"form_base: {len(forms):,} 行 / {summary['form_base']['distinct_old']} 类"
          f"（检测试剂 {summary['form_base']['diagnostic_rows']}）")
    print(f"规格异常: {len(bad):,} 行；无规格产品: {len(nos):,}")
    print(f"批文: {len(appr):,} 行 {dict(kinds)}")
    print(f"精确重复: {summary['dup_exact']['groups']} 组 / 删除 {len(dups):,} 行")
    print(f"待复核标记: {summary['dup_review']['groups']} 组 / {len(pend):,} 行")
    print(f"summary {WORK / 'dryrun.json'}")
    return 0


# ---------------------------------------------------------------- apply / rollback
def _snapshot_product(con: sqlite3.Connection, pid: str) -> str:
    prod = con.execute("SELECT * FROM product WHERE product_id=?", (pid,)).fetchone()
    cols = [d[0] for d in con.execute("SELECT * FROM product WHERE product_id=?",
                                      (pid,)).description]
    comps = []
    for r in con.execute("SELECT * FROM product_component WHERE product_id=?",
                         (pid,)).fetchall():
        comps.append(list(r))
    names = [list(r) for r in con.execute(
        "SELECT product_id, key_id, name_type, is_primary FROM product_name "
        "WHERE product_id=?", (pid,)).fetchall()]
    snap = {"product": dict(zip(cols, prod)), "components": comps,
            "component_cols": ["product_id", "ord", "variant_id", "strength_value",
                               "strength_unit", "per_volume_value", "per_volume_unit"],
            "names": names}
    return json.dumps(snap, ensure_ascii=False)


def _journal(con: sqlite3.Connection, run_id: str, step: str, pid: str,
             field: str, old, new) -> None:
    con.execute(
        """INSERT INTO cleanup_cn_journal
           (run_id, step, product_id, field, old_value, new_value, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (run_id, step, pid, field,
         None if old is None else str(old), None if new is None else str(new), _now()))


def _rollback_run(con: sqlite3.Connection, run_id: str, verbose: bool = True) -> dict:
    stats = Counter()
    # 1) 恢复 journal 字段
    for r in con.execute(
            "SELECT step, product_id, field, old_value, new_value FROM cleanup_cn_journal "
            "WHERE run_id=? ORDER BY rowid DESC", (run_id,)).fetchall():
        step, pid, field, old, new = r
        if field == "note":
            con.execute("UPDATE product SET note=? WHERE product_id=?",
                        (old, pid) if old is not None else (None, pid))
        elif field.startswith(("strength_value@", "strength_unit@",
                               "per_volume_value@", "per_volume_unit@")):
            fld, _, ord_s = field.partition("@")
            con.execute(f"UPDATE product_component SET {fld}=? "
                        "WHERE product_id=? AND ord=?",
                        (None if old is None else _parse_value(old), pid, int(ord_s)))
        else:
            con.execute(f"UPDATE product SET {field}=? WHERE product_id=?",
                        (None if old is None else old, pid))
        stats[step] += 1
    # 2) 恢复被删产品（快照）
    for pid, snap_json in con.execute(
            "SELECT product_id, snapshot FROM cleanup_cn_deleted_product WHERE run_id=?",
            (run_id,)).fetchall():
        snap = json.loads(snap_json)
        prod = snap["product"]
        if con.execute("SELECT 1 FROM product WHERE product_id=?", (pid,)).fetchone():
            continue
        cols = list(prod)
        con.execute(f"INSERT INTO product ({', '.join(cols)}) VALUES "
                    f"({', '.join('?' * len(cols))})", [prod[c] for c in cols])
        for row in snap["components"]:
            con.execute("INSERT OR IGNORE INTO product_component "
                        "(product_id, ord, variant_id, strength_value, strength_unit, "
                        "per_volume_value, per_volume_unit) VALUES (?,?,?,?,?,?,?)", row)
        for row in snap["names"]:
            con.execute("INSERT OR IGNORE INTO product_name "
                        "(product_id, key_id, name_type, is_primary) VALUES (?,?,?,?)", row)
        stats["restored_products"] += 1
    # 3) 清 review / journal / backup
    stats["review_rows"] = con.execute(
        "DELETE FROM cleanup_cn_dup_review WHERE run_id=?", (run_id,)).rowcount
    stats["journal_rows"] = con.execute(
        "DELETE FROM cleanup_cn_journal WHERE run_id=?", (run_id,)).rowcount
    stats["deleted_rows"] = con.execute(
        "DELETE FROM cleanup_cn_deleted_product WHERE run_id=?", (run_id,)).rowcount
    if verbose:
        print(f"rollback {run_id}: {dict(stats)}")
    return dict(stats)


def _set_note_marker(con: sqlite3.Connection, run_id: str, step: str, pid: str,
                     marker: str) -> bool:
    row = con.execute("SELECT note FROM product WHERE product_id=?", (pid,)).fetchone()
    old = row["note"] if row else None
    new = add_marker(old, marker)
    if new == (old or ""):
        return False
    _journal(con, run_id, step, pid, "note", old, new)
    con.execute("UPDATE product SET note=? WHERE product_id=?", (new, pid))
    return True


def cmd_apply(args: argparse.Namespace) -> int:
    _guard_real(args.db, args.allow_real)
    if not args.db.exists():
        raise SystemExit(f"DB 不存在：{args.db}")
    con = sqlite3.connect(args.db, timeout=180)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(DDL)
        con.execute("PRAGMA foreign_keys=ON")
        run_id = args.run_id
        # 幂等：先回滚同 run_id 的旧结果（若存在）
        have_old = con.execute("SELECT 1 FROM cleanup_cn_journal WHERE run_id=? LIMIT 1",
                               (run_id,)).fetchone() or con.execute(
            "SELECT 1 FROM cleanup_cn_deleted_product WHERE run_id=? LIMIT 1",
            (run_id,)).fetchone()
        if have_old:
            with con:
                _rollback_run(con, run_id, verbose=True)
        forms = scan_form(con)
        bad = scan_strength_bad(con)
        nos = scan_no_strength(con)
        appr = scan_approval(con)
        dups = scan_exact_dups(con)
        pend = scan_pending_review(con)
        stats = Counter()
        with con:
            # 0) 先快照「将被去重删除」的产品（必须是清洗前的原始状态，供回滚）
            dup_snaps = {}
            for d in dups:
                dup_snaps[d["product_id"]] = _snapshot_product(con, d["product_id"])
            # 1) form_base
            for f in forms:
                if (f["old"] or "") == f["new"]:
                    continue
                _journal(con, run_id, "form_base", f["product_id"], "form_base",
                         f["old"], f["new"])
                con.execute("UPDATE product SET form_base=? WHERE product_id=?",
                            (f["new"], f["product_id"]))
                stats["form_base"] += 1
                if f["diagnostic"]:
                    if _set_note_marker(con, run_id, "form_base",
                                        f["product_id"], MARK_DIAG):
                        stats["diagnostic"] += 1
            # 2) 规格异常 → NULL + note
            for b in bad:
                pid, ord_ = b["product_id"], b["ord"]
                old = {"strength_value": b["strength_value"],
                       "strength_unit": b["strength_unit"],
                       "per_volume_value": b["per_volume_value"],
                       "per_volume_unit": b["per_volume_unit"]}
                for field, val in old.items():
                    _journal(con, run_id, "strength", pid, f"{field}@{ord_}", val, None)
                con.execute(
                    """UPDATE product_component SET strength_value=NULL, strength_unit=NULL,
                       per_volume_value=NULL, per_volume_unit=NULL
                       WHERE product_id=? AND ord=?""", (pid, ord_))
                _set_note_marker(con, run_id, "strength", pid, MARK_STRENGTH_BAD)
                stats["strength_nulled"] += 1
            # 3) 无规格标记
            for pid in nos:
                if _set_note_marker(con, run_id, "no_strength", pid, MARK_NO_STRENGTH):
                    stats["no_strength"] += 1
            # 4) 批文
            for a in appr:
                pid = a["product_id"]
                _journal(con, run_id, "approval", pid, "approval_id", a["old"], a["new"])
                con.execute("UPDATE product SET approval_id=? WHERE product_id=?",
                            (a["new"], pid))
                if a["note_marker"]:
                    marker = a["note_marker"]
                    if MARK_APPROVAL_RAW in marker and a["old"] is not None:
                        marker += "=" + str(a["old"])
                    _set_note_marker(con, run_id, "approval", pid, marker)
                stats["approval"] += 1
            # 5) 精确重复删除（使用步骤 0 的原始快照）
            for d in dups:
                snap = dup_snaps[d["product_id"]]
                con.execute(
                    """INSERT OR REPLACE INTO cleanup_cn_deleted_product
                       (run_id, product_id, keeper_id, snapshot, created_at)
                       VALUES (?,?,?,?,?)""",
                    (run_id, d["product_id"], d["keeper_id"], snap, _now()))
                con.execute("DELETE FROM product WHERE product_id=?", (d["product_id"],))
                stats["dup_deleted"] += 1
            # 6) 待复核标记
            for p in pend:
                con.execute(
                    """INSERT OR IGNORE INTO cleanup_cn_dup_review
                       (run_id, product_id, group_key, reason, created_at)
                       VALUES (?,?,?,?,?)""",
                    (run_id, p["product_id"], p["group_key"], p["reason"], _now()))
                stats["dup_review"] += 1
        summary = {"db": str(args.db), "run_id": run_id, "applied_at": _now(),
                   "counts": dict(stats),
                   "remaining": {
                       "form_noncanon": len(scan_form(con)),
                       "bad_strength": len(scan_strength_bad(con)),
                       "no_strength": len(scan_no_strength(con)),
                       "approval_changed": len(scan_approval(con))}}
        (WORK / "apply.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
        print(f"=== CN cleanup apply（{args.db}）===")
        print(f"counts={dict(stats)}")
        print(f"remaining={summary['remaining']}")
        return 0
    finally:
        con.close()


def cmd_rollback(args: argparse.Namespace) -> int:
    if not args.db.exists():
        raise SystemExit(f"DB 不存在：{args.db}")
    con = sqlite3.connect(args.db, timeout=180)
    try:
        con.executescript(DDL)
        with con:
            _rollback_run(con, args.run_id)
        return 0
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CN 数据清洗批次（form_base/规格/重复/批文）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只统计（默認）")
    mode.add_argument("--apply", action="store_true", help="寫入（默認限副本）")
    mode.add_argument("--rollback", action="store_true", help="回滾本次 run_id")
    ap.add_argument("--run-id", default=DEFAULT_RUN_ID)
    ap.add_argument("--allow-real", action="store_true",
                    help="允許寫 data/drugs.db（需窗口 + 備份）")
    args = ap.parse_args(argv)
    if args.rollback:
        return cmd_rollback(args)
    if args.apply:
        return cmd_apply(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
