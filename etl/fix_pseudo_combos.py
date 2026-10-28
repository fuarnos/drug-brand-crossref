# -*- coding: utf-8 -*-
"""伪复方（base+salt 被当多成分）审计与修复（task-137）。

识别
----
1) **产品级**：同一 product 的多个 component 指向不同 substance，但 substance 名为
   「碱基 B」与「B + 盐/水合物/酯 词」关系（严格：长名 = 短名 + 全部 salt token）→
   该产品不是复方，是同一活性成分的重复成分。
2) **key 级**（build 索引 vs 联合）：同一 name_key 下多个产品的成分并集出现
   「B 与 B+salt」→ 索引 `x` 显示 `A + A salt`、生成 combo 页、触发 collision。
   这一类不是单个产品重复，而是**同一 base 的 salt substance 被多个产品/来源当成不同成分**；
   修复需在 build 层按 base 归并，或做 substance 归并（跨产品），不能删单产品成分解决。

产物
----
- `data/pseudo_combo_issues.csv`：受影响 key + 产品（key_norm/key_id/product/country/
  source/substances/base/relation/fix_mode/recommend）
- `--apply --db <副本>`：只做**产品级安全修复**（保留 base 成分、删除重复 salt 成分、重排 ord），
  写撤销清单；`--rollback` 精确恢复。

用法
----
    python etl/fix_pseudo_combos.py --dry-run
    python etl/fix_pseudo_combos.py --db .tmp/pseudo-combo/test.db --apply
    python etl/fix_pseudo_combos.py --db .tmp/pseudo-combo/test.db --rollback
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "drugs.db"
OUT_CSV = ROOT / "data" / "pseudo_combo_issues.csv"
WORK = ROOT / ".tmp" / "pseudo-combo"
DEFAULT_MANIFEST = WORK / "fix_manifest.json"

SALT = {"hydrochloride", "hydrobromide", "sodium", "potassium", "calcium", "magnesium",
        "sulfate", "sulphate", "phosphate", "acetate", "fumarate", "maleate", "succinate",
        "tartrate", "citrate", "mesylate", "besylate", "tosylate", "besilate", "tosilate",
        "nitrate", "gluconate", "lactate", "chloride", "bromide", "iodide", "oxide",
        "carbonate", "bicarbonate", "benzoate", "pamoate", "embonate", "palmitate",
        "stearate", "decanoate", "enanthate", "cypionate", "undecanoate", "propionate",
        "valerate", "furoate", "xinafoate", "hyclate", "estolate", "mesilate", "hydrate",
        "monohydrate", "dihydrate", "trihydrate", "tetrahydrate", "hemihydrate",
        "sesquihydrate", "anhydrous", "solvate", "ethanolate", "ester", "hcl", "hbr"}
ELEMENTS = {"sodium", "potassium", "calcium", "magnesium", "chloride", "bromide",
            "iodide", "oxide", "carbonate", "bicarbonate", "sulfate", "sulphate",
            "phosphate", "nitrate", "lactate", "acetate", "citrate", "tartrate",
            "gluconate", "maleate", "fumarate", "succinate"}


def norm(s: str) -> str:
    s = (s or "").lower().replace("(", " ").replace(")", " ").replace("-", " ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_salt_of(short: str, long_: str) -> bool:
    if not short or len(short) < 4 or short in ELEMENTS or short in SALT:
        return False
    if not long_.startswith(short + " "):
        return False
    rest = long_[len(short):].split()
    return bool(rest) and all(w in SALT for w in rest)


def connect(p: Path, write=False):
    return sqlite3.connect(p, timeout=120) if write else sqlite3.connect(
        f"file:{p.as_posix()}?mode=ro", uri=True, timeout=120)


def load(db) -> dict:
    db.row_factory = sqlite3.Row
    subs = {r[0]: r[1] for r in db.execute("select substance_id,inn_en from substance")}
    nsub = {sid: norm(inn) for sid, inn in subs.items()}
    comps = defaultdict(list)
    for r in db.execute("""select pc.product_id,pc.ord,pc.variant_id,v.substance_id,
                                  pc.strength_value,pc.strength_unit,
                                  pc.per_volume_value,pc.per_volume_unit,
                                  p.country,p.source_id
                           from product_component pc
                           join product p on p.product_id=pc.product_id
                           join variant v on v.variant_id=pc.variant_id
                           order by pc.product_id,pc.ord"""):
        comps[r[0]].append(dict(r))
    pn = defaultdict(list)       # product -> keys
    key_prods = defaultdict(set)
    for pid, kid in db.execute("select product_id,key_id from product_name"):
        pn[pid].append(kid)
        key_prods[kid].add(pid)
    prod_subs = {pid: {c["substance_id"] for c in cs} for pid, cs in comps.items()}
    key_subs = defaultdict(set)
    for kid, pids in key_prods.items():
        s = set()
        for pid in pids:
            s |= prod_subs.get(pid, set())
        key_subs[kid] = s
    kn = {r[0]: r[1] for r in db.execute("select key_id,norm from name_key")}
    return {"subs": subs, "nsub": nsub, "comps": comps, "prod_keys": pn,
            "key_prods": key_prods, "key_subs": key_subs, "kn": kn}


def _strip_salt(n: str) -> str:
    words = n.split()
    while len(words) > 1 and words[-1] in SALT:
        words.pop()
    return " ".join(words)


def product_pairs(d: dict) -> dict:
    """产品级：按「碱基族」找出重复的 salt 成分（可多族）。

    规则：若产品内存在 substance B（nsub[B] 恰为碱基名）与 substance S
    （nsub[S] = B 的碱基名 + 盐/水合物/酯词），则 S 是 B 的重复成分，删除 S、保留 B。
    多个族（如 TPN 里多种氨基酸/电解质的 base+salt）逐一处理；没有 base 成分的组不删。
    """
    out = {}
    for pid, cs in d["comps"].items():
        if len(cs) < 2:
            continue
        by_name = {}
        for c in cs:
            by_name.setdefault(d["nsub"][c["substance_id"]], []).append(c["substance_id"])
        families = []
        delete = set()
        used = set()
        for c in cs:
            sid = c["substance_id"]
            if sid in used:
                continue
            base_name = _strip_salt(d["nsub"][sid])
            if not base_name or base_name == d["nsub"][sid]:
                continue
            base_ids = [b for b in by_name.get(base_name, []) if b != sid]
            if not base_ids:
                continue
            # S 是 base 的盐型重复；保留 base
            families.append((base_ids[0], [sid]))
            delete.add(sid)
            used.add(sid)
        if families:
            out[pid] = {"families": families, "delete": sorted(delete), "n": len(cs)}
    return out


def key_pairs(d: dict) -> dict:
    out = {}
    for kid, sids in d["key_subs"].items():
        if len(sids) < 2:
            continue
        base = min(sids, key=lambda s: len(d["nsub"][s]))
        ok = True
        for s in sids:
            if s == base or d["nsub"][s] == d["nsub"][base]:
                continue
            if not is_salt_of(d["nsub"][base], d["nsub"][s]):
                ok = False
                break
        if ok and len(sids) > 1:
            out[kid] = {"base": base, "subs": sorted(sids)}
    return out


def write_csv(d: dict, pp: dict, kp: dict, path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    key_seen = set()
    for kid, info in sorted(kp.items()):
        for pid in sorted(d["key_prods"][kid]):
            cs = d["comps"].get(pid) or []
            subs = sorted({d["subs"].get(c["substance_id"], "") for c in cs})
            rows.append([d["kn"].get(kid, kid), kid, d["subs"].get(info["base"], ""),
                         pid, cs[0]["country"] if cs else "", cs[0]["source_id"] if cs else "",
                         len(cs), " | ".join(subs), "key_level(base+salt 跨产品)",
                         "build 按 base 归并", "自动仅改 build/index；数据层需 substance 归并"])
        key_seen.add(kid)
    for pid, info in sorted(pp.items()):
        cs = d["comps"].get(pid) or []
        subs = sorted({d["subs"].get(c["substance_id"], "") for c in cs})
        families = ",".join(
            f"{d['subs'].get(b, b)} ← {d['subs'].get(s, s)}"
            for b, salts in info["families"] for s in salts)
        rows.append(["", "", d["subs"].get(info["families"][0][0], ""), pid,
                     cs[0]["country"] if cs else "", cs[0]["source_id"] if cs else "",
                     len(cs), " | ".join(subs), f"product_level({families})",
                     "保留 base 成分，删除 salt 重复成分", "可自动修复（副本）"])
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["key_norm", "key_id", "base_substance", "product_id", "country",
                    "source_id", "n_components", "substances", "relation", "recommend",
                    "fix_mode"])
        w.writerows(rows)
    return {"csv_rows": len(rows), "ks": len(kp), "pp": len(pp)}


def cmd_dry_run(args) -> int:
    d = load(connect(args.db))
    pp = product_pairs(d)
    kp = key_pairs(d)
    stats = write_csv(d, pp, kp, args.out)
    by_market = Counter()
    for kid, info in kp.items():
        for pid in d["key_prods"][kid]:
            cs = d["comps"].get(pid)
            if cs:
                by_market[cs[0]["country"]] += 1
    print("=== 伪复方 dry-run ===")
    print(f"key 级伪复方: {len(kp)} key / 涉及产品 {sum(len(d['key_prods'][k]) for k in kp):,}")
    print("市场分布（key 级涉及产品）:", dict(by_market))
    print(f"产品级重复成分: {len(pp)} 产品（可自动修复）")
    print("CSV:", args.out, stats)
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "dryrun.json").write_text(json.dumps({
        "key_pairs": {d["kn"].get(k, k): [d["subs"][s] for s in v["subs"]] for k, v in kp.items()},
        "product_pairs": {k: {
            "families": [[d["subs"][b], [d["subs"][s] for s in salts]]
                         for b, salts in v["families"]],
            "delete": [d["subs"][s] for s in v["delete"]]} for k, v in pp.items()},
        "markets": dict(by_market), "stats": stats}, ensure_ascii=False, indent=1), encoding="utf-8")
    for kid in list(kp)[:15]:
        print(" ", d["kn"].get(kid), "→", [d["subs"][s] for s in kp[kid]["subs"]])
    return 0


def cmd_apply(args) -> int:
    if args.db.resolve() == DEFAULT_DB.resolve() and not args.allow_real:
        raise SystemExit("拒绝写真实库：先副本验证；窗口需 --allow-real")
    d = load(connect(args.db))
    pp = product_pairs(d)
    db = connect(args.db, write=True)
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    prev = None
    if manifest_path.exists():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prev = None
    if prev and prev.get("db") != str(args.db):
        prev = None
    merged = {x["product_id"]: x for x in (prev or {}).get("products", [])}
    manifest = {"tool": "etl/fix_pseudo_combos.py", "db": str(args.db),
                "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "products": []}
    removed = 0
    try:
        db.execute("BEGIN IMMEDIATE")
        for pid, info in pp.items():
            cs = d["comps"][pid]
            delete_sids = set(info["delete"])
            old_rows = [dict(c) for c in cs]
            delete_ords = [c["ord"] for c in cs if c["substance_id"] in delete_sids]
            if not delete_ords:
                continue
            db.execute(f"DELETE FROM product_component WHERE product_id=? AND ord IN "
                       f"({','.join('?' * len(delete_ords))})", [pid, *delete_ords])
            removed += len(delete_ords)
            # 剩余行重排 ord
            remain = [c for c in cs if c["ord"] not in delete_ords]
            db.execute("UPDATE product_component SET ord=ord+1000 WHERE product_id=?", (pid,))
            for i, c in enumerate(sorted(remain, key=lambda x: x["ord"])):
                db.execute("UPDATE product_component SET ord=? WHERE product_id=? AND ord=?",
                           (i, pid, c["ord"] + 1000))
            item = {"product_id": pid, "old": old_rows, "deleted_ords": delete_ords}
            if pid not in merged:          # 保留首次 apply 的原始状态
                merged[pid] = item
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    manifest["products"] = list(merged.values())
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"=== 产品级修复完成：{len(pp)} 产品，删除 {removed} 行（清单累计 {len(manifest['products'])} 产品）===")
    print("撤销清单:", manifest_path)
    return 0


def cmd_rollback(args) -> int:
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    if not manifest_path.exists():
        raise SystemExit(f"找不到撤销清单：{manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    db = connect(args.db, write=True)
    restored = 0
    try:
        db.execute("BEGIN IMMEDIATE")
        for item in data.get("products", []):
            pid = item["product_id"]
            db.execute("DELETE FROM product_component WHERE product_id=?", (pid,))
            for c in item["old"]:
                db.execute("""INSERT INTO product_component
                              (product_id,ord,variant_id,strength_value,strength_unit,
                               per_volume_value,per_volume_unit)
                              VALUES (?,?,?,?,?,?,?)""",
                           (pid, c["ord"], c["variant_id"], c["strength_value"],
                            c["strength_unit"], c.get("per_volume_value"), c.get("per_volume_unit")))
            restored += 1
        db.commit()
    finally:
        db.close()
    print(f"=== 回滚完成：{restored} 产品恢复原成分行 ===")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="伪复方（base+salt）审计与产品级修复（task-137）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只统计 + 写 CSV（默认）")
    mode.add_argument("--apply", action="store_true", help="产品级修复（默认限副本）")
    mode.add_argument("--rollback", action="store_true", help="按撤销清单回滚")
    ap.add_argument("--allow-real", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT_CSV)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = ap.parse_args(argv)
    if args.rollback:
        return cmd_rollback(args)
    if args.apply:
        return cmd_apply(args)
    return cmd_dry_run(args)


if __name__ == "__main__":
    sys.exit(main())
