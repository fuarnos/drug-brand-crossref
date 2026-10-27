#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GB dm+d 盐型恢复：把「dm+d 原料名里的盐」补回 variant，并把 GB 组件改挂到盐 variant。

背景
----
`etl/ingest_dmd.py` 用 VTM（干净通用名）建 variant（`vid = sid`），把 VMP→VPI（虚拟产品
成分）指向的 dm+d 原料名（INGREDIENT，如 "Amlodipine besilate"、
"Atorvastatin calcium trihydrate"）里的盐型丢掉了。本脚本只读解析
`data/raw/dmd/extracted/` 最新包的三个文件，恢复有明确证据的 (substance, salt)：

    f_amp2_*.xml        APID → VPID（一个 AMP 对应一个 VMP）
    f_vmp2_*.xml        VPID → VPI(ISID...)  （VMP 的成分引用）
    f_ingredient2_*.xml ISID → 原料名（含盐型词）

安全边界（只做「能唯一判定」的，绝不猜）
----------------------------------------
1. 只处理 `country='GB' AND source_id='dmd'` 的产品；
2. 要求该产品恰好 1 个 product_component，且当前 variant 是 base（salt 为空）；
3. 要求 AMP→VMP 存在且 VMP 恰好 1 个 VPI（复方跳过）；ISID 原料名存在且未被 INVALID；
4. 原料名 = 「该成分的现有基名（substance.inn_en / substance_id 归一）」+「盐后缀」，
   基名必须**精确匹配**；盐后缀用 `etl/normalize_salts.classify_salt` 归一；
5. 盐后缀必须是单一盐（kind='salt'）或「单一盐+水合物」（kind='salt_hydrate'，水合物
   另存 `variant.hydrate`）；mixed / non_salt / 酯 / 溶剂化物 / 多盐一律跳过；
6. 目标 variant：优先复用现有同 (substance, salt_code, 水合物) 的 variant；同盐多个
   variant → 跳过（歧义）；没有才新建。**不删任何 variant/substance**，只改组件指向；
7. 幂等：已挂到盐 variant 的组件不再进入计划；重复 apply 写入 0。

CLI
---
    python etl/fix_dmd_salts.py --dry-run                 # 默认；只读 DB + 解析 XML，出计划
    python etl/fix_dmd_salts.py --apply --confirm-real-db  # 写库（事务 + 撤销清单）
    python etl/fix_dmd_salts.py --apply --db .tmp/dmd-salt/snapshot.db   # 副本验证（推荐）
    python etl/fix_dmd_salts.py --rollback                 # 用最近一次撤销清单回滚
    python etl/fix_dmd_salts.py --verify                   # 只读统计恢复后覆盖

产物：计划 CSV / 撤销清单 JSON 落 `.tmp/dmd-salt/`。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
from normalize_salts import (  # noqa: E402
    WATER_TOKENS, classify_salt, has_salt_code_column,
)

DB_DEFAULT = ROOT / "data" / "drugs.db"
RAW_DIR = ROOT / "data" / "raw" / "dmd"
WORK_DIR = ROOT / ".tmp" / "dmd-salt"
PLAN_CSV = WORK_DIR / "dryrun_plan.csv"

# salt_code 是 data/salt_base_fraction.csv 的代码；只接受单一盐（不含 mixed/non_salt）
ALLOWED_KINDS = {"salt", "salt_hydrate"}


# ---------------------------------------------------------------------------
# 文件名 / 版本
# ---------------------------------------------------------------------------
def find_files(raw_dir: Path = RAW_DIR) -> tuple[Path, Path, Path, str]:
    """找最新一版 f_ingredient2 / f_vmp2 / f_amp2（版本后缀一致）。"""
    roots = [raw_dir / "extracted", raw_dir]
    ing_files: list[Path] = []
    for r in roots:
        if r.is_dir():
            ing_files.extend(sorted(r.glob("f_ingredient2_*.xml"), key=lambda p: p.stat().st_mtime))
    if not ing_files:
        raise SystemExit(f"找不到 f_ingredient2_*.xml（已找 {raw_dir}）")
    ing = ing_files[-1]
    version = ing.stem.rsplit("_", 1)[-1]
    base = ing.parent
    vmp = base / f"f_vmp2_{version}.xml"
    amp = base / f"f_amp2_{version}.xml"
    for p in (vmp, amp):
        if not p.exists():
            raise SystemExit(f"缺少同版本文件: {p}")
    return ing, vmp, amp, version


# ---------------------------------------------------------------------------
# XML 解析（iterparse，只拿需要的字段）
# ---------------------------------------------------------------------------
def parse_ingredients(path: Path) -> tuple[dict[str, str], dict[str, bool]]:
    """ISID → 原料名；INVALID 标记。"""
    names: dict[str, str] = {}
    invalid: dict[str, bool] = {}
    for _ev, el in ET.iterparse(path, events=("end",)):
        if el.tag == "ING":
            fields = {c.tag: (c.text or "").strip() for c in el}
            isid = fields.get("ISID", "")
            if isid:
                names[isid] = fields.get("NM", "")
                invalid[isid] = "INVALID" in fields
            el.clear()
    return names, invalid


def parse_vmps(path: Path) -> dict[str, dict]:
    """VPID → {nm, ingredients:[(isid, basis, strength)]}。

    dm+d v2 版式：root=VIRTUAL_MED_PRODUCTS，子容器 VMPS 里是 <VMP>，
    成分引用是**同级**的 <VPI>（VIRTUAL_PRODUCT_INGREDIENT 记录），不是 VMP 的子元素；
    所以要一次扫描分别收集 VMP / VPI，再按 VPID 合并。
    """
    vmps: dict[str, dict] = {}
    vpis: dict[str, list[tuple[str, str, str]]] = {}
    for _ev, el in ET.iterparse(path, events=("end",)):
        if el.tag == "VMP":
            f = {c.tag: (c.text or "").strip() for c in el}
            vpid = f.get("VPID", "")
            if vpid:
                vmps[vpid] = {"nm": f.get("NM", ""), "ingredients": []}
            el.clear()
        elif el.tag == "VPI":
            f = {c.tag: (c.text or "").strip() for c in el}
            vpid = f.get("VPID", "")
            if vpid:
                vpis.setdefault(vpid, []).append(
                    (f.get("ISID", ""), f.get("BASIS_STRNTCD", ""),
                     f.get("STRNT_NMRTR_VAL", "")))
            el.clear()
    for vpid, ings in vpis.items():
        if vpid in vmps:
            vmps[vpid]["ingredients"] = ings
    return vmps


def parse_amps(path: Path) -> dict[str, dict]:
    """APID → {nm, vpid}。"""
    out: dict[str, dict] = {}
    for _ev, el in ET.iterparse(path, events=("end",)):
        if el.tag == "AMP":
            fields = {c.tag: (c.text or "").strip() for c in el}
            apid = fields.get("APID", "")
            if apid:
                out[apid] = {"nm": fields.get("NM", ""), "vpid": fields.get("VPID", "")}
            el.clear()
    return out


# ---------------------------------------------------------------------------
# 名称/盐型工具
# ---------------------------------------------------------------------------
def norm(s: str) -> str:
    """归一：去重音、小写、非字母数字→空格、压空格。"""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s.lower())).strip()


def water_tokens_of(phrase: str) -> list[str]:
    toks = [t for t in norm(phrase).split() if t]
    return [t for t in toks if t in WATER_TOKENS]


def split_ingredient_salt(nm: str, base_names: set[str]) -> tuple[str, str, object] | None:
    """原料名 → (base_text, salt_phrase, SaltNorm)；不匹配返回 None。

    从尾部 1..4 个词开始试：盐短语能被 classify_salt 归一为单一盐/盐+水合物，
    且去掉盐短语后的前缀恰好等于该成分的已归一基名之一。
    """
    toks = norm(nm).split()
    for k in range(1, 5):
        if len(toks) <= k:
            break
        phrase = " ".join(toks[-k:])
        sn = classify_salt(phrase)
        if sn.kind not in ALLOWED_KINDS or not sn.salt_code:
            continue
        if sn.salt_code in ("mixed", "non_salt"):
            continue
        prefix = " ".join(toks[:-k])
        if prefix in base_names:
            return prefix, phrase, sn
    return None


def base_names_of(con: sqlite3.Connection, sid: str) -> set[str]:
    row = con.execute("SELECT substance_id, inn_en FROM substance WHERE substance_id=?",
                      (sid,)).fetchone()
    if not row:
        return set()
    out = {norm(row["substance_id"].replace("-", " "))}
    if row["inn_en"]:
        out.add(norm(row["inn_en"]))
    return {x for x in out if x}


def variant_id_for(sid: str, salt_code: str, waters: list[str]) -> str:
    vid = f"{sid}-{salt_code}"
    if waters:
        vid += "-" + "-".join(waters)
    return re.sub(r"[^a-z0-9-]+", "-", vid.lower()).strip("-")


# ---------------------------------------------------------------------------
# 计划
# ---------------------------------------------------------------------------
def build_plan(con: sqlite3.Connection, ing: dict[str, str], invalid: dict[str, bool],
               vmp: dict[str, dict], amp: dict[str, dict]) -> dict:
    existing_variants: dict[str, list[dict]] = {}
    for r in con.execute(
            "SELECT variant_id, substance_id, salt, salt_code, hydrate FROM variant"):
        existing_variants.setdefault(r["substance_id"], []).append(dict(r))

    rows = con.execute(
        """SELECT p.product_id, pc.variant_id, pc.ord, v.substance_id, v.salt,
                  v.salt_code, v.hydrate, s.inn_en
           FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id
           JOIN substance s ON s.substance_id = v.substance_id
           WHERE p.country='GB' AND p.source_id='dmd'
           ORDER BY p.product_id, pc.ord""").fetchall()
    by_product: dict[str, list] = {}
    for r in rows:
        by_product.setdefault(r["product_id"], []).append(r)

    plan: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    def skip(product_id, reason, **kw):
        skipped.append(dict(product_id=product_id, reason=reason, **kw))

    for pid, parts in by_product.items():
        if len(parts) != 1:
            skip(pid, f"combo/multi-component n={len(parts)}")
            continue
        part = parts[0]
        if part["salt_code"] or part["salt"]:
            continue                      # 已经是盐 variant（幂等/其它来源已修）
        if part["ord"] != 0:
            skip(pid, "ord!=0")
            continue
        apid = pid[3:] if pid.startswith("GB-") else ""
        a = amp.get(apid)
        if not a:
            skip(pid, "AMP 缺失")
            continue
        v = vmp.get(a["vpid"])
        if not v:
            skip(pid, "VMP 缺失")
            continue
        if len(v["ingredients"]) != 1:
            skip(pid, f"VMP 成分数 n={len(v['ingredients'])}（复方）")
            continue
        isid = v["ingredients"][0][0]
        nm = ing.get(isid, "")
        if not nm:
            skip(pid, f"原料名缺失 ISID={isid}")
            continue
        if invalid.get(isid):
            skip(pid, f"原料名已 INVALID ISID={isid}")
            continue
        base_names = base_names_of(con, part["substance_id"])
        split = split_ingredient_salt(nm, base_names)
        if split is None:
            skip(pid, f"原料名无匹配盐后缀: {nm!r}")
            continue
        _base, phrase, sn = split
        waters = water_tokens_of(phrase)

        # 找目标 variant：同 (salt_code, 水合物词集) 唯一
        cands = []
        for ev in existing_variants.get(part["substance_id"], []):
            code = ev["salt_code"] or classify_salt(ev["salt"] or "").salt_code
            if code != sn.salt_code:
                continue
            ev_water = sorted(water_tokens_of((ev["salt"] or "") + " " + (ev["hydrate"] or "")))
            if ev_water == sorted(waters):
                cands.append(ev)
        if len(cands) > 1:
            skip(pid, f"同盐 variant 歧义 {[c['variant_id'] for c in cands]}", salt=sn.salt_code)
            continue
        if cands:
            target = cands[0]["variant_id"]
            action = "reuse"
        else:
            target = variant_id_for(part["substance_id"], sn.salt_code, waters)
            clash = con.execute(
                "SELECT substance_id, salt, salt_code FROM variant WHERE variant_id=?",
                (target,)).fetchone()
            if clash is not None:
                # 常见于库里有「盐名 substance」（如 aciclovir-sodium 自己一个 substance，
                # 其 base variant_id 恰好占用目标 id）；不覆盖、不合并，交给人工/后续任务。
                where = ("同成分但 salt_code 不一致" if clash["substance_id"] == part["substance_id"]
                         else f"被其它 substance 占用: {clash['substance_id']}")
                skip(pid, f"variant_id 冲突（{where}）: {target}", salt=sn.salt_code)
                continue
            action = "create"

        plan.append(dict(
            product_id=pid, ord=part["ord"], apid=apid, vpid=a["vpid"],
            substance_id=part["substance_id"], inn_en=part["inn_en"],
            from_variant=part["variant_id"], to_variant=target, action=action,
            salt_code=sn.salt_code, salt_phrase=phrase,
            salt=" ".join(t for t in norm(phrase).split() if t not in WATER_TOKENS),
            hydrate=" ".join(waters), ingredient=nm, vmp=tuple(v["nm"]) if v["nm"] else "",
            kind=sn.kind))

    return dict(plan=plan, skipped=skipped, errors=errors, scanned=len(by_product))


def print_plan(p: dict) -> None:
    plan = p["plan"]
    to_create = [x for x in plan if x["action"] == "create"]
    to_reuse = [x for x in plan if x["action"] == "reuse"]
    create_vids = {x["to_variant"] for x in to_create}
    reuse_vids = {x["to_variant"] for x in to_reuse}
    print(f"扫描 GB dm+d 产品: {p['scanned']}")
    print(f"可恢复产品/组件: {len(plan)} 个组件（{len({x['product_id'] for x in plan})} 个产品）")
    print(f"目标 variant: 新建 {len(create_vids)} 个 / 复用 {len(reuse_vids)} 个"
          f"（新建覆盖组件 {len(to_create)}，复用覆盖组件 {len(to_reuse)}）")
    print(f"涉及成分: {len({x['substance_id'] for x in plan})}")
    if plan:
        print("盐型分布:", dict(Counter(x["salt_code"] for x in plan).most_common(20)))
        print("涉及成分 Top 15:", dict(Counter(x["inn_en"] for x in plan).most_common(15)))
        print("\n样例（前 15）:")
        for x in sorted(plan, key=lambda y: y["substance_id"])[:15]:
            print(f"  {x['product_id']:<28} {x['inn_en']:<26} {x['from_variant']:<24} -> "
                  f"{x['to_variant']:<32} [{x['salt_code']}] 原料名={x['ingredient']!r}")
    if p["errors"]:
        print(f"\n!! 错误 {len(p['errors'])} 条:")
        for e in p["errors"][:10]:
            print("   ", e)
    if p["skipped"]:
        hist = Counter(re.sub(r"n=\d+|ISID=\S+|\{.*\}|'.*?'", "", s["reason"]) for s in p["skipped"])
        print(f"\n跳过 {len(p['skipped'])} 个产品，原因分布（去参数）:")
        for reason, n in hist.most_common(12):
            print(f"   {n:>6}  {reason}")
        print("   明细样例（前 8）:")
        for s in p["skipped"][:8]:
            print(f"   {s['product_id']}  {s['reason']}")


def write_plan_csv(p: dict) -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    cols = ["product_id", "ord", "substance_id", "inn_en", "salt_code", "salt",
            "hydrate", "from_variant", "to_variant", "action", "kind",
            "ingredient", "vmp", "apid", "vpid"]
    with open(PLAN_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for x in p["plan"]:
            w.writerow({k: x.get(k, "") for k in cols})


# ---------------------------------------------------------------------------
# DB 连接 / apply / rollback
# ---------------------------------------------------------------------------
def connect(path: Path, write: bool) -> sqlite3.Connection:
    if write:
        con = sqlite3.connect(str(path), timeout=120)
    else:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def guard_real_db(db_path: Path, action: str, confirmed: bool) -> None:
    try:
        is_real = db_path.resolve() == DB_DEFAULT.resolve()
    except OSError:
        is_real = False
    if is_real and action in ("apply", "rollback") and not confirmed:
        raise SystemExit(
            f"拒绝在真实库上 {action}：请用 --db 指向副本（如 .tmp/dmd-salt/snapshot.db）验证，"
            "或显式加 --confirm-real-db 并在无并行写库时执行。")


def cmd_dry_run(args) -> int:
    ing, vmp, amp, version = find_files()
    print(f"dm+d 版本: {version}  ({amp.parent})")
    print("解析:", ing.name, vmp.name, amp.name, flush=True)
    ing_names, ing_invalid = parse_ingredients(ing)
    vmps = parse_vmps(vmp)
    amps = parse_amps(amp)
    print(f"  ingredient={len(ing_names)}  vmp={len(vmps)}  amp={len(amps)}")
    con = connect(Path(args.db), write=False)
    try:
        p = build_plan(con, ing_names, ing_invalid, vmps, amps)
    finally:
        con.close()
    print()
    print_plan(p)
    write_plan_csv(p)
    print(f"\n计划 CSV: {PLAN_CSV}")
    print("(dry-run，未写库。加 --apply（副本）执行)")
    return 0


def cmd_apply(args) -> int:
    db_path = Path(args.db)
    guard_real_db(db_path, "apply", args.confirm_real_db)
    ing, vmp, amp, version = find_files()
    ing_names, ing_invalid = parse_ingredients(ing)
    vmps = parse_vmps(vmp)
    amps = parse_amps(amp)
    con = connect(db_path, write=True)
    try:
        p = build_plan(con, ing_names, ing_invalid, vmps, amps)
        plan = p["plan"]
        if not plan:
            print("没有可恢复项（幂等：可能已 apply 过）")
            print_plan(p)
            return 0
        if p["errors"]:
            print(f"!! 存在 {len(p['errors'])} 条错误，拒绝 apply", file=sys.stderr)
            return 1
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        manifest = WORK_DIR / f"undo_{stamp}.json"
        created: list[dict] = []
        moved: list[dict] = []
        data = {"version": version, "db": str(db_path), "applied_at": stamp,
                "created_variants": created, "moved_components": moved}
        try:
            for x in plan:
                if x["action"] == "create" and not any(
                        c["variant_id"] == x["to_variant"] for c in created):
                    con.execute(
                        "INSERT INTO variant (variant_id, substance_id, salt, hydrate,"
                        " ester, base_fraction, interchange, interchange_note, salt_code)"
                        " VALUES (?,?,?,?, '', 1.0, 'unknown', NULL, ?)",
                        (x["to_variant"], x["substance_id"], x["salt"], x["hydrate"],
                         x["salt_code"]))
                    created.append(dict(variant_id=x["to_variant"],
                                        substance_id=x["substance_id"],
                                        salt=x["salt"], hydrate=x["hydrate"],
                                        salt_code=x["salt_code"]))
                cur = con.execute(
                    "UPDATE product_component SET variant_id=?"
                    " WHERE product_id=? AND ord=? AND variant_id=?",
                    (x["to_variant"], x["product_id"], x["ord"], x["from_variant"]))
                if cur.rowcount != 1:
                    raise SystemExit(
                        f"组件更新失败（预期 1 行，实际 {cur.rowcount}）: "
                        f"{x['product_id']}#{x['ord']}")
                moved.append(dict(product_id=x["product_id"], ord=x["ord"],
                                  from_variant=x["from_variant"],
                                  to_variant=x["to_variant"]))
            manifest.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                encoding="utf-8")
            con.commit()
        except BaseException:
            con.rollback()
            raise
        print_plan(p)
        print(f"\napply 完成：新建 variant {len(created)}，改挂组件 {len(moved)}")
        print(f"撤销清单: {manifest}")
        return 0
    finally:
        con.close()


def latest_manifest() -> Path | None:
    cands = sorted(WORK_DIR.glob("undo_*.json"), key=lambda p: p.stat().st_mtime)
    return cands[-1] if cands else None


def cmd_rollback(args) -> int:
    path = Path(args.manifest) if args.manifest else latest_manifest()
    if path is None or not path.exists():
        raise SystemExit(f"找不到撤销清单（{WORK_DIR}）")
    db_path = Path(args.db)
    guard_real_db(db_path, "rollback", args.confirm_real_db)
    data = json.loads(path.read_text(encoding="utf-8"))
    con = connect(db_path, write=True)
    try:
        restored = 0
        try:
            for m in data["moved_components"]:
                con.execute(
                    "UPDATE product_component SET variant_id=?"
                    " WHERE product_id=? AND ord=? AND variant_id=?",
                    (m["from_variant"], m["product_id"], m["ord"], m["to_variant"]))
                restored += 1
            removed = 0
            for v in data["created_variants"]:
                used = con.execute(
                    "SELECT COUNT(*) FROM product_component WHERE variant_id=?",
                    (v["variant_id"],)).fetchone()[0]
                if used == 0:
                    con.execute("DELETE FROM variant WHERE variant_id=?", (v["variant_id"],))
                    removed += 1
            con.commit()
        except BaseException:
            con.rollback()
            raise
        print(f"回滚完成：还原组件 {restored}，删除新建 variant {removed}（清单 {path.name}）")
        return 0
    finally:
        con.close()


def cmd_verify(args) -> int:
    con = connect(Path(args.db), write=False)
    try:
        q = lambda s: con.execute(s).fetchone()[0]
        print("variant 总数:", q("SELECT COUNT(*) FROM variant"))
        print("salt_code 非空:", q("SELECT COUNT(*) FROM variant WHERE coalesce(salt_code,'')<>''"))
        print("GB dmd 产品:", q("SELECT COUNT(*) FROM product WHERE country='GB' AND source_id='dmd'"))
        print("GB dmd 组件挂 salt variant:", q("""
            SELECT COUNT(*) FROM product p JOIN product_component pc ON pc.product_id=p.product_id
            JOIN variant v ON v.variant_id=pc.variant_id
            WHERE p.country='GB' AND p.source_id='dmd' AND coalesce(v.salt_code,'')<>''"""))
        print("GB dmd 组件挂 base variant:", q("""
            SELECT COUNT(*) FROM product p JOIN product_component pc ON pc.product_id=p.product_id
            JOIN variant v ON v.variant_id=pc.variant_id
            WHERE p.country='GB' AND p.source_id='dmd' AND coalesce(v.salt,'')=''"""))
        print("integrity_check:", q("PRAGMA integrity_check"))
    finally:
        con.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GB dm+d 盐型恢复（默认 dry-run）")
    ap.add_argument("--db", default=str(DB_DEFAULT), help="SQLite 数据库（apply 请用副本）")
    ap.add_argument("--apply", action="store_true", help="写库（事务 + 撤销清单）")
    ap.add_argument("--dry-run", action="store_true", help="只出计划（默认）")
    ap.add_argument("--rollback", action="store_true", help="按最近撤销清单回滚")
    ap.add_argument("--verify", action="store_true", help="打印恢复覆盖统计")
    ap.add_argument("--manifest", default=None, help="指定撤销清单（rollback 用）")
    ap.add_argument("--confirm-real-db", action="store_true", help="允许对真实库 apply/rollback")
    args = ap.parse_args(argv)
    if args.verify:
        return cmd_verify(args)
    if args.rollback:
        return cmd_rollback(args)
    if args.apply:
        return cmd_apply(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
