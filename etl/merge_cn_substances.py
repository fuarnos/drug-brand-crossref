#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把「只有中文名」的 CN 专属成分（substance_id = cn-*）合并到已有英文 INN 成分。

用法
----
    # 默认 dry-run：只读打开数据库，打印将合并的 id 对、组件数、跳过原因
    python etl/merge_cn_substances.py

    # 真正写库（事务内 UPDATE product_component、DELETE variant/substance）
    python etl/merge_cn_substances.py --apply

    # 用撤销清单回滚（缺省取 .tmp/cn-map/ 下最新的 merge_undo_*.json）
    python etl/merge_cn_substances.py --rollback
    python etl/merge_cn_substances.py --rollback .tmp/cn-map/merge_undo_xxx.json

输入
----
`data/cn_inn_overrides.csv`（UTF-8，可带 BOM），列：
    zh_name,en_inn,cn_substance_id,en_substance_id,evidence_url,confidence,status,reason
只有 status == "mergeable" 的行会被处理；no_english / combination / uncertain 只统计。

安全校验（任何一条不过就跳过该行，绝不部分合并）
------------------------------------------------
1. CN 侧 substance 存在、id 以 cn- 开头（本工具只删 cn-*，永不删英文成分）
2. 英文目标 substance 存在、id 不以 cn- 开头，且 inn_en 与 CSV 的 en_inn 归一化后一致
3. CN 侧恰好 1 个 variant，且 salt/hydrate/ester 全空（base variant），base_fraction≈1
4. 英文目标恰好 1 个 base variant（salt/hydrate/ester 全空），把 CN 的组件挂到它上面
5. CN 侧成分没有被 nickname / drug_term / confusable_pair / dose_warning（若表存在）引用
6. 将被移动的产品没有 corroboration 记录（人工核对过的产品保持原样）
7. 幂等：CN 成分已不存在（上一轮已合并）→ 记为 already_merged，不报错
8. CSV 内同一 cn_substance_id 出现多次且目标不一致 → 全部跳过

撤销清单
--------
--apply 在提交前把完整的 substance 行、variant 行、被移动的 product_component
(product_id, ord, 旧 variant_id) 写入 JSON（默认 .tmp/cn-map/merge_undo_<UTC>.json），
并写入 committed 标记；--rollback 按清单逆序重建并按 (product_id, ord) 精确回挂。
清单自身可重复回滚（第二次会全部记为 already_restored）。

注意：本轮验证只在 .tmp/cn-map/ 的 DB 副本上跑 --apply；正式库请先 --dry-run。
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
CSV_DEFAULT = ROOT / "data" / "cn_inn_overrides.csv"
MANIFEST_DIR = ROOT / ".tmp" / "cn-map"

CSV_COLUMNS = [
    "zh_name", "en_inn", "cn_substance_id", "en_substance_id",
    "evidence_url", "confidence", "status", "reason",
]
PROCESS_STATUS = "mergeable"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm_name(s: str) -> str:
    """英文名归一化：NFKC、小写、标点→空格、压缩空格。"""
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def has_latin(s: str) -> bool:
    return bool(re.search(r"[A-Za-z]", s or ""))


# ---------------------------------------------------------------------------
# CSV
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
    # 同一 cn_substance_id 出现多次：目标一致则去重，不一致则全部标记冲突
    by_cn: dict[str, list[dict]] = {}
    for r in rows:
        by_cn.setdefault(r["cn_substance_id"], []).append(r)
    dedup: list[dict] = []
    seen: set[str] = set()
    for cn_id, group in by_cn.items():
        targets = {r["en_substance_id"] for r in group}
        if len(targets) > 1:
            errors.append(f"{cn_id} 在 CSV 中出现 {len(group)} 次且目标不一致: {sorted(targets)}")
            continue
        r = dict(group[0])
        if len(group) > 1:
            r["_csv_dups"] = len(group)
        if cn_id not in seen:
            seen.add(cn_id)
            dedup.append(r)
    return dedup, errors


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def connect(db_path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = "file:" + str(db_path).replace("?", "%3f") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=60)
    else:
        con = sqlite3.connect(str(db_path), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def base_variants(con: sqlite3.Connection, substance_id: str) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT * FROM variant
           WHERE substance_id=? AND COALESCE(salt,'')='' AND COALESCE(hydrate,'')=''
             AND COALESCE(ester,'')=''""",
        (substance_id,),
    ).fetchall()


# 中文盐/酯词 → variant.salt / variant.ester 里可能出现的英文写法
ZH_MOD_TO_EN = {
    "盐酸": "hydrochloride", "氢溴酸": "hydrobromide", "硫酸": "sulfate",
    "甲磺酸": "mesylate", "甲苯磺酸": "tosylate", "对甲苯磺酸": "tosylate",
    "苯磺酸": "besylate", "马来酸": "maleate", "富马酸": "fumarate",
    "琥珀酸": "succinate", "半琥珀酸": "succinate", "酒石酸": "tartrate",
    "枸橼酸": "citrate", "柠檬酸": "citrate", "醋酸": "acetate", "乙酸": "acetate",
    "磷酸": "phosphate", "乳酸": "lactate", "硝酸": "nitrate",
    "葡萄糖酸": "gluconate", "门冬氨酸": "aspartate", "天冬氨酸": "aspartate",
    "棕榈酸": "palmitate", "硬脂酸": "stearate", "戊酸": "valerate",
    "丙酸": "propionate", "二丙酸": "dipropionate", "丁酸": "butyrate",
    "草酸": "oxalate", "苯甲酸": "benzoate", "水杨酸": "salicylate",
    "葡萄糖醛酸": "glucuronate", "乳糖酸": "lactobionate",
    "氯铵": "chloride", "溴铵": "bromide", "碘铵": "iodide",
}
HYDRATE_ZH = {"七水": "heptahydrate", "三水": "trihydrate",
              "二水": "dihydrate", "一水": "monohydrate"}


def zh_modifier_set(zh: str) -> set[str]:
    """中文名里的盐/酯/水合写法 → 英文修饰词集合。"""
    mods = {en for zh_tok, en in ZH_MOD_TO_EN.items() if zh_tok in zh}
    mods |= {en for zh_tok, en in HYDRATE_ZH.items() if zh_tok in zh}
    return mods


def pick_target_variant(con: sqlite3.Connection, en_sid: str,
                        zh: str) -> tuple[sqlite3.Row | None, str, str]:
    """给英文目标挑一个 variant：优先盐/酯/水合对得上的，其次唯一 base variant。

    返回 (variant_row, mode, reason_if_none)。mode ∈ salt_variant / base。
    """
    vs = all_variants(con, en_sid)
    if not vs:
        return None, "", "英文目标没有任何 variant 行"
    mods = zh_modifier_set(zh)
    matched = [v for v in vs
               if mods and ((v["salt"] or "") in mods or (v["ester"] or "") in mods
                            or (v["hydrate"] or "") in mods)]
    if len(matched) == 1:
        return matched[0], "salt_variant", ""
    if len(matched) > 1:
        return None, "", f"英文目标有 {len(matched)} 个盐/酯/水合 variant 与中文名匹配，无法唯一确定"
    bases = [v for v in vs
             if not (v["salt"] or "") and not (v["hydrate"] or "")
             and not (v["ester"] or "")]
    if len(bases) == 1:
        mode = "base_fallback" if mods else "base"
        return bases[0], mode, ""
    if not bases:
        return None, "", "英文目标没有空盐/水合/酯的 base variant"
    return None, "", f"英文目标 base variant 数={len(bases)}（要求恰好 1 个）"


def all_variants(con: sqlite3.Connection, substance_id: str) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM variant WHERE substance_id=?", (substance_id,)).fetchall()


def count_products_of_variant(con: sqlite3.Connection, variant_id: str) -> int:
    return con.execute(
        "SELECT COUNT(DISTINCT product_id) FROM product_component WHERE variant_id=?",
        (variant_id,),
    ).fetchone()[0]


def ref_counts(con: sqlite3.Connection, cn_sid: str, variant_ids: list[str]) -> dict[str, int]:
    """CN 成分被哪些表引用。"""
    out = {"nickname": 0, "drug_term": 0, "confusable_pair": 0}
    out["nickname"] = con.execute(
        "SELECT COUNT(*) FROM nickname WHERE substance_id=?", (cn_sid,)).fetchone()[0]
    if table_exists(con, "drug_term"):
        out["drug_term"] = con.execute(
            "SELECT COUNT(*) FROM drug_term WHERE substance_id=?", (cn_sid,)).fetchone()[0]
    out["confusable_pair"] = con.execute(
        "SELECT COUNT(*) FROM confusable_pair"
        " WHERE a_substance_id=? OR b_substance_id=?", (cn_sid, cn_sid)).fetchone()[0]
    if table_exists(con, "dose_warning"):
        out["dose_warning"] = con.execute(
            "SELECT COUNT(*) FROM dose_warning"
            " WHERE substance_id=? OR related_substance_id=?", (cn_sid, cn_sid)).fetchone()[0]
    corr = 0
    if variant_ids:
        qs = ",".join("?" * len(variant_ids))
        corr = con.execute(
            f"""SELECT COUNT(*) FROM corroboration c
                WHERE EXISTS (SELECT 1 FROM product_component pc
                              WHERE pc.product_id=c.product_id
                                AND pc.variant_id IN ({qs}))""",
            variant_ids,
        ).fetchone()[0]
    out["corroboration_products"] = corr
    return out


# ---------------------------------------------------------------------------
# 计划（dry-run 与 apply 共用）
# ---------------------------------------------------------------------------
def plan(con: sqlite3.Connection, rows: list[dict], verbose: bool = False) -> dict:
    status_counts = Counter(r["status"] for r in rows)
    accepted: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    for r in rows:
        st = r["status"]
        if st != PROCESS_STATUS:
            continue  # 非 mergeable 只统计
        cn_sid = r["cn_substance_id"]
        en_sid = r["en_substance_id"]
        why = None
        level = "skip"

        cn_row = con.execute("SELECT * FROM substance WHERE substance_id=?", (cn_sid,)).fetchone()
        en_row = con.execute("SELECT * FROM substance WHERE substance_id=?", (en_sid,)).fetchone()

        if not cn_sid.startswith("cn-"):
            why, level = f"cn_substance_id 不是 cn-* : {cn_sid}", "error"
        elif not cn_row:
            # 幂等：上一轮已合并
            why, level = "already_merged（CN 成分子库中已不存在）", "skip"
        elif not en_sid:
            why, level = "en_substance_id 为空", "error"
        elif not en_row:
            why, level = f"英文目标不存在: {en_sid}", "error"
        elif en_sid.startswith("cn-"):
            why, level = f"英文目标仍是 cn-* 成分: {en_sid}", "error"
        elif not has_latin(en_row["inn_en"]):
            why, level = f"英文目标的 inn_en 非法: {en_row['inn_en']!r}", "error"
        elif en_sid == cn_sid:
            why, level = "CN 与 EN 目标相同", "error"
        elif norm_name(en_row["inn_en"]) != norm_name(r["en_inn"]):
            why, level = (f"en_inn 不一致: CSV={r['en_inn']!r} DB={en_row['inn_en']!r}", "error")

        cn_vars = all_variants(con, cn_sid) if cn_row else []
        en_variant: sqlite3.Row | None = None
        variant_mode = ""
        if why is None and len(cn_vars) != 1:
            why = f"CN 侧 variant 数={len(cn_vars)}（要求恰好 1 个）"
        if why is None:
            v = cn_vars[0]
            salt, hyd, est = (v["salt"] or ""), (v["hydrate"] or ""), (v["ester"] or "")
            if salt or hyd or est:
                why = f"CN 侧不是 base variant: salt={salt!r} hydrate={hyd!r} ester={est!r}"
            elif abs((v["base_fraction"] if v["base_fraction"] is not None else 1.0) - 1.0) > 1e-9:
                why = f"CN 侧 base_fraction={v['base_fraction']}（要求 1.0）"
        if why is None:
            en_variant, variant_mode, vwhy = pick_target_variant(con, en_sid, r["zh_name"])
            if en_variant is None:
                why = vwhy
        if why is None:
            refs = ref_counts(con, cn_sid, [cn_vars[0]["variant_id"]])
            if refs["nickname"]:
                why = f"nickname 引用 {refs['nickname']} 条"
            elif refs["drug_term"]:
                why = f"drug_term 引用 {refs['drug_term']} 条"
            elif refs["confusable_pair"]:
                why = f"confusable_pair 引用 {refs['confusable_pair']} 条"
            elif refs.get("dose_warning"):
                why = f"dose_warning 引用 {refs['dose_warning']} 条"
            elif refs["corroboration_products"]:
                why = f"受影响产品有 corroboration {refs['corroboration_products']} 条"

        if why is not None:
            (errors if level == "error" else skipped).append(dict(
                cn_sid=cn_sid, en_sid=en_sid, zh=r["zh_name"], en=r["en_inn"], reason=why))
            continue

        cn_v = cn_vars[0]
        en_v = en_variant
        pcs = con.execute(
            "SELECT product_id, ord, variant_id FROM product_component WHERE variant_id=?"
            " ORDER BY product_id, ord", (cn_v["variant_id"],)).fetchall()
        n_products = len({p["product_id"] for p in pcs})
        accepted.append(dict(
            zh_name=r["zh_name"], en_inn=r["en_inn"],
            cn_sid=cn_sid, en_sid=en_sid,
            cn_variant_id=cn_v["variant_id"], en_variant_id=en_v["variant_id"],
            variant_mode=variant_mode,
            n_components=len(pcs), n_products=n_products,
            cn_substance=dict(cn_row), cn_variant=dict(cn_v),
            product_components=[dict(p) for p in pcs],
            evidence_url=r["evidence_url"], confidence=r["confidence"],
            csv_dups=r.get("_csv_dups", 1),
        ))
        if verbose:
            print(f"  OK {r['zh_name']} ({n_products} 产品) {cn_sid} -> {en_sid}")

    return dict(rows=rows, status_counts=status_counts, accepted=accepted,
                skipped=skipped, errors=errors)


def print_plan(p: dict) -> None:
    rows = p["rows"]
    sc: Counter = p["status_counts"]
    accepted = p["accepted"]
    print(f"CSV 行数: {len(rows)}  mergeable 行: {sc.get(PROCESS_STATUS, 0)}")
    print("状态分布: " + ", ".join(f"{k}={v}" for k, v in sorted(sc.items())))
    print(f"可合并: {len(accepted)} 个 CN 成分 -> 英文成分")
    print(f"受影响产品(去重): {sum(a['n_products'] for a in accepted)}")
    print(f"将移动 product_component 行: {sum(a['n_components'] for a in accepted)}")
    print(f"将删除 variant: {len(accepted)}，删除 substance: {len(accepted)}")
    mode_counts: Counter = Counter(a["variant_mode"] for a in accepted)
    if mode_counts:
        print("目标 variant 选择: " + ", ".join(
            f"{k}={v}" for k, v in sorted(mode_counts.items())))
    fallback = mode_counts.get("base_fallback", 0)
    if fallback:
        print(f"  其中 {fallback} 条中文名带盐/酯但目标无对应 variant，按 base variant 合并")
    zero = [a for a in accepted if a["n_components"] == 0]
    if zero:
        print(f"其中 0 产品的成分子（孤儿）: {len(zero)}")
    if p["errors"]:
        print(f"\n!! CSV/DB 校验错误 {len(p['errors'])} 条（这些行不会被合并）:")
        for e in p["errors"][:20]:
            print(f"   {e['cn_sid']} {e['zh']} -> {e['en_sid']}: {e['reason']}")
    by_reason: Counter = Counter()
    for s in p["skipped"]:
        key = re.sub(r"[\d:='\"]+", "N", s["reason"]).split("（")[0]
        by_reason[key] += 1
    if p["skipped"]:
        print(f"\n跳过 {len(p['skipped'])} 行，原因分布:")
        for k, v in by_reason.most_common():
            print(f"   {v:>4}  {k}")
        print("   明细（前 20）:")
        for s in p["skipped"][:20]:
            print(f"   {s['cn_sid']} {s['zh']} -> {s['en_sid']}: {s['reason']}")
    if accepted:
        print("\n计划合并清单（按产品数排序）:")
        print(f"  {'产品':>5} {'组件':>5}  {'cn 成分':<14} {'中文名':<16} 英文目标")
        for a in sorted(accepted, key=lambda x: (-x["n_products"], x["zh_name"])):
            print(f"  {a['n_products']:>5} {a['n_components']:>5}  {a['cn_sid']:<14}"
                  f" {a['zh_name']:<16} {a['en_sid']} ({a['en_inn']})")


# ---------------------------------------------------------------------------
# apply / rollback
# ---------------------------------------------------------------------------
def apply(con: sqlite3.Connection, p: dict, db_path: Path, csv_path: Path,
          manifest_path: Path) -> int:
    accepted = p["accepted"]
    if not accepted:
        print("没有可合并的行（幂等或全部被跳过），未写库。")
        return 0
    manifest = {
        "tool": "etl/merge_cn_substances.py",
        "db": str(db_path.resolve()),
        "csv": str(csv_path.resolve()),
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest()
        if csv_path.exists() else "",
        "created_at": utc_now(),
        "committed": False,
        "merges": [],
    }
    merged = 0
    try:
        con.execute("BEGIN IMMEDIATE")
        for a in accepted:
            rec = {
                "zh_name": a["zh_name"], "en_inn": a["en_inn"],
                "cn_substance_id": a["cn_sid"], "en_substance_id": a["en_sid"],
                "cn_variant_id": a["cn_variant_id"], "en_variant_id": a["en_variant_id"],
                "variant_mode": a["variant_mode"],
                "cn_substance_row": a["cn_substance"],
                "cn_variant_row": a["cn_variant"],
                "product_components": a["product_components"],
                "n_products": a["n_products"],
                "evidence_url": a["evidence_url"], "confidence": a["confidence"],
            }
            con.execute(
                "UPDATE product_component SET variant_id=? WHERE variant_id=?",
                (a["en_variant_id"], a["cn_variant_id"]))
            con.execute("DELETE FROM variant WHERE variant_id=?", (a["cn_variant_id"],))
            cur = con.execute("DELETE FROM substance WHERE substance_id=?", (a["cn_sid"],))
            if cur.rowcount != 1:
                raise RuntimeError(f"删除 substance {a['cn_sid']} 影响 {cur.rowcount} 行，中止")
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
    print(f"已合并 {merged} 个 CN 成分；撤销清单: {manifest_path}")
    return merged


def rollback(con: sqlite3.Connection, manifest_path: Path) -> None:
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
            cn_sid = rec["cn_substance_id"]
            cn_vid = rec["cn_variant_id"]
            en_vid = rec.get("en_variant_id") or rec.get("en_base_variant_id")
            sub = rec["cn_substance_row"]
            var = rec["cn_variant_row"]
            if not con.execute("SELECT 1 FROM substance WHERE substance_id=?",
                               (rec["en_substance_id"],)).fetchone():
                raise SystemExit(f"英文目标 {rec['en_substance_id']} 已不存在，拒绝回滚")
            if not con.execute("SELECT 1 FROM variant WHERE variant_id=?", (en_vid,)).fetchone():
                raise SystemExit(f"英文 base variant {en_vid} 已不存在，拒绝回滚")
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
                    (cn_vid, pc["product_id"], pc["ord"], en_vid))
                if cur.rowcount == 0:
                    # 已经回滚过（组件已指回 cn variant）→ 幂等跳过；否则记为冲突
                    still = con.execute(
                        "SELECT variant_id FROM product_component WHERE product_id=? AND ord=?",
                        (pc["product_id"], pc["ord"])).fetchone()
                    if not still:
                        conflicts.append(f"组件已不存在: {rec['zh_name']} "
                                         f"{pc['product_id']}#{pc['ord']}")
                    elif still["variant_id"] == cn_vid:
                        pass
                    else:
                        conflicts.append(f"组件指向已变化: {rec['zh_name']} "
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
        description="把 CN 专属成分（cn-*）合并到已有英文 INN 成分（默认 dry-run）。")
    ap.add_argument("--csv", default=str(CSV_DEFAULT), help="覆盖映射 CSV")
    ap.add_argument("--db", default=str(DB_DEFAULT), help="SQLite 数据库")
    ap.add_argument("--apply", action="store_true", help="真正写库（事务 + 撤销清单）")
    ap.add_argument("--dry-run", action="store_true", help="只出计划（默认行为）")
    ap.add_argument("--rollback", nargs="?", const="latest", default=None,
                    help="回滚：可给清单路径，缺省取 .tmp/cn-map/ 最新清单")
    ap.add_argument("--manifest", default=None,
                    help="--apply 的撤销清单路径（默认 .tmp/cn-map/merge_undo_<UTC>.json）")
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
        p = plan(con, rows, verbose=args.verbose)
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
