"""Q3 T3 盐基表 40 → 68：`variant.base_fraction` / `strength_basis` 回填（只在盐型有出处时）。

输入
  - `data/sources/salt_map_20261115.csv`：68 行「盐代码 → 反离子」表（本窗口逐行复核，见 §复核）；
  - `data/salt_base_fraction.csv`：既有 40 行「盐代码 → n_base / increment_mw」，37 行有 PubChem
    分子量核对示例；
  - `etl/apply_salt_fractions.BASE_MW`：27 个碱基分子量（PubChem 逐条核对）。

公式（只用质量分数，**不做任何剂量换算、不输出等效剂量**）：

    f = n·M(base) / (n·M(base) + Δ + k·18.015)
    Δ = 反离子增量（金属盐 = 离子 MW − n·H；胺盐 = 整酸 MW；酯 = 酸 MW − H2O）
    k = variant.hydrate 里的结晶水个数（无水 0、半水 0.5、一水 1、三水 3…）

写入条件（同时满足，否则只统计不写）：
  1. `variant.salt_code` 在复核后的盐表里且 `status='usable'`；
  2. 该 substance 的碱基分子量已知（BASE_MW）；
  3. `base_fraction` 仍是默认 1.0（不覆盖人工值）。

CLI：
    python db/q3_apply_salt_map.py --review                  # 打印 68 行复核表（不写库）
    python db/q3_apply_salt_map.py --apply --db <副本> --manifest <json>
    python db/q3_apply_salt_map.py --rollback --db <副本> --manifest <json>
真实库写需显式 `--allow-real`（先备份 data/drugs.db）。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "etl" / "markets"))
from _ingest_common import connect, guard_real, sha256_file  # noqa: E402
from apply_salt_fractions import BASE_MW  # noqa: E402

DEFAULT_DB = ROOT / "data" / "drugs.db"
SALT_MAP = ROOT / "data" / "sources" / "salt_map_20261115.csv"
OLD_CSV = ROOT / "data" / "salt_base_fraction.csv"
DEFAULT_MANIFEST = ROOT / "data" / "sources" / "salt_fraction_manifest_20261118.json"
REVIEW_CSV = ROOT / "data" / "sources" / "salt_map_review_20261118.csv"
WATER = 18.015

# 复核后的折算规则：salt_code → (n_base, increment_mw, status, note)
# status：usable = 可自动折算；note = 化学计量依具体原料药而不能自动折算（只登记不写）；
#         exclude = 明确不可自动折算（复盐/溶剂化物）。
# 依据：旧表 data/salt_base_fraction.csv 已核值 + IUPAC 2021 原子量逐条重算（本窗口复核）。
RULES: dict[str, tuple[int, float, str, str]] = {
    # ---- 金属阳离子盐：Δ = 离子 MW − n·H（n_base = 阳离子价数） ----
    "sodium": (1, 21.982, "usable", "Na(22.990)−H(1.008)；旧表已核，PubChem 左甲状腺素钠 0.9725"),
    "potassium": (1, 38.09, "usable", "K(39.098)−H；旧表已核"),
    "calcium": (2, 38.062, "usable", "Ca(40.078)−2H；旧表已核，PubChem 阿托伐他汀钙 0.9670"),
    "magnesium": (2, 22.289, "usable", "Mg(24.305)−2H；旧表已核，PubChem 奥美拉唑镁 0.9687"),
    "zinc": (2, 63.364, "usable", "Zn(65.380)−2H（salt_map 只给离子 65.38，未减 H）"),
    "aluminium": (3, 23.958, "usable", "Al(26.982)−3H（salt_map 只给离子 26.982）"),
    "lithium": (1, 5.932, "usable", "Li(6.940)−H（salt_map 只给离子 6.94）"),
    "ammonium": (1, 17.031, "usable", "NH4(18.039)−H（胺成盐：碱+HCl 型反离子 NH3 增量）"),
    # ---- 胺/无机的酸式盐：Δ = 整酸 MW ----
    "hydrochloride": (1, 36.458, "usable", "HCl；旧表已核，PubChem 盐酸舍曲林 0.8935"),
    "hydrobromide": (1, 80.912, "usable", "HBr；旧表"),
    "hydriodide": (1, 127.912, "usable", "HI；旧表（iodide 系同理）"),
    "nitrate": (1, 63.012, "usable", "HNO3(63.012)；salt_map 的 62.005 是 NO3⁻ 离子，未加 H"),
    "sulfate": (2, 98.072, "usable", "H2SO4(98.072)，2 碱:1 酸；旧表已核"),
    "hydrogensulfate": (1, 98.072, "usable", "H2SO4 整酸（1:1 硫酸氢盐）；salt_map 的 97.07 是 HSO4⁻ 离子"),
    "phosphate": (1, 97.994, "usable", "H3PO4，1:1（磷酸可待因型）；salt_map 写 n=3 是价数而非计量比"),
    "dihydrogenphosphate": (1, 97.994, "usable", "H3PO4，1:1 二氢磷酸盐"),
    "hydrogenphosphate": (2, 97.994, "usable", "H3PO4(97.994)，2 碱:1 酸（HPO4²⁻）"),
    "acetate": (1, 60.052, "usable", "C2H4O2；旧表已核"),
    "lactate": (1, 90.078, "usable", "C3H6O3；旧表已核"),
    "citrate": (1, 192.123, "usable", "C6H8O7 整酸，1:1（枸橼酸西地那非 0.7119 已核）；"
                                       "salt_map 写 n=3 是价数，2:3 盐需另核"),
    "maleate": (2, 116.072, "usable", "C4H4O4，2 碱:1 酸；旧表"),
    "fumarate": (2, 116.072, "usable", "C4H4O4，2 碱:1 酸；旧表已核（富马酸喹硫平 0.8685）"),
    "succinate": (2, 118.088, "usable", "C4H6O4，2 碱:1 酸；旧表已核（琥珀酸美托洛尔 0.8191）"),
    "tartrate": (2, 150.086, "usable", "C4H6O6，2 碱:1 酸；旧表已核（酒石酸美托洛尔 0.7808）"),
    "oxalate": (2, 90.034, "usable", "C2H2O4，2 碱:1 酸（草酸盐通常 2:1）"),
    "benzoate": (1, 122.123, "usable", "C7H6O2；旧表"),
    "salicylate": (1, 138.122, "usable", "C7H6O3（水杨酸）"),
    "gluconate": (1, 196.155, "usable", "C6H12O7；旧表"),
    "glucoheptonate": (1, 226.181, "usable", "C7H14O8（葡庚糖酸）"),
    "lactobionate": (1, 358.296, "usable", "C12H22O12（乳糖酸）"),
    "glutamate": (1, 147.13, "usable", "C5H9NO4（谷氨酸）"),
    "malate": (1, 134.087, "usable", "C4H6O5（苹果酸）"),
    "aspartate": (1, 133.103, "usable", "C4H7NO4；旧表"),
    "pamoate": (2, 388.375, "usable", "C23H16O6（双羟萘酸），2:1；旧表"),
    "besylate": (1, 158.171, "usable", "C6H6O3S；旧表已核（苯磺酸氨氯地平 0.7210）"),
    "mesylate": (1, 96.106, "usable", "CH4O3S；旧表（96.100 为同一值四舍五入差）"),
    "tosylate": (1, 172.198, "usable", "C7H8O3S；旧表"),
    "xinafoate": (1, 188.182, "usable", "C11H8O3（昔萘酸）；旧表"),
    "napsylate": (1, 208.231, "usable", "C10H8O3S 整酸；salt_map 的 207.248 是离子，未加 H"),
    "edisylate": (2, 190.19, "usable", "C2H6O6S2（乙二磺酸 190.19），2 碱:1 酸；"
                                       "salt_map 的 109.145 与乙二磺酸分子量不符，按 IUPAC 重算"),
    # ---- 胺类反离子（酸性药物成盐） ----
    "tromethamine": (1, 121.136, "usable", "C4H11NO3；旧表"),
    "meglumine": (1, 195.215, "usable", "C7H17NO5；旧表"),
    "trolamine": (1, 149.189, "usable", "C6H15NO3（三乙醇胺）"),
    "diethylamine": (1, 73.139, "usable", "C4H11N"),
    "ethylenediamine": (2, 60.1, "note", "C2H8N2 二价，化学计量依原料药（1:1 / 2:1）"),
    "piperazine": (2, 86.138, "note", "C4H10N2 二价，化学计量依原料药"),
    # ---- 酯类：Δ = 酸 MW − H2O（成酯脱一分子水） ----
    "furoate": (1, 94.069, "usable", "C5H4O3(112.084)−H2O；旧表已核"),
    "valerate": (1, 84.118, "usable", "C5H10O2(102.133)−H2O；旧表"),
    "propionate": (1, 56.064, "usable", "C3H6O2(74.079)−H2O；旧表"),
    "dipropionate": (1, 112.128, "usable", "2×(C3H6O2−H2O)；旧表"),
    "butyrate": (1, 70.091, "usable", "C4H8O2(88.106)−H2O"),
    "pivalate": (1, 84.118, "usable", "C5H10O2(102.133)−H2O"),
    "aceponate": (1, 168.153, "usable", "C22H30O6 型酸 186.168−H2O（salt_map 值减水）"),
    "buteprate": (1, 140.181, "usable", "C3H6O2+丁酸型混合酯 158.196−H2O"),
    "probate": (1, 140.181, "usable", "buteprate 的旧写法（同一酯），158.196−H2O"),
    "decanoate": (1, 154.253, "usable", "C10H20O2(172.268)−H2O；旧表"),
    "enanthate": (1, 112.172, "usable", "C7H14O2(130.187)−H2O；旧表"),
    "cypionate": (1, 124.183, "usable", "C8H14O2(142.198)−H2O；旧表；"
                                        "salt_map 的 150.196 与环戊丙酸分子量不符，按 IUPAC 重算"),
    "palmitate": (1, 238.415, "usable", "C16H32O2(256.430)−H2O；旧表"),
    "stearate": (1, 266.469, "usable", "C18H36O2(284.484)−H2O；旧表"),
    # ---- 水合物 / 无水物：Δ = k·H2O（variant.hydrate 另计，这里只登记单价） ----
    "anhydrous": (1, 0.0, "usable", "无水物：Δ=0（f=1）"),
    "hemihydrate": (1, 9.008, "usable", "0.5·H2O"),
    "monohydrate": (1, 18.015, "usable", "1·H2O"),
    "dihydrate": (1, 36.03, "usable", "2·H2O"),
    "sesquihydrate": (1, 27.023, "usable", "1.5·H2O"),
    "trihydrate": (1, 54.045, "usable", "3·H2O"),
    "pentahydrate": (1, 90.076, "usable", "5·H2O"),
    # ---- 季铵/卤化物（salt_map 68 行里没有，但旧表 40 行有：直接沿用旧表值，避免口径倒退） ----
    "chloride": (1, 35.45, "usable", "Cl(35.450)（季铵阳离子 + Cl⁻）；旧表 40 行有、salt_map 缺"),
    "bromide": (1, 79.904, "usable", "Br(79.904)；旧表 40 行有、salt_map 缺"),
    "iodide": (1, 127.912, "usable", "HI(127.912)（胺氢碘酸盐）；旧表 40 行有、salt_map 缺"),
    # ---- 不可自动折算 ----
    "hyclate": (1, 0.0, "exclude", "多西环素 hyclate = 盐酸盐·½乙醇·½水（复盐+溶剂化物），"
                                   "分子量必须按具体原料药核对；旧表也是 manual_review"),
}

HYDRATE_K = {"": 0.0, "anhydrous": 0.0, "hemihydrate": 0.5, "monohydrate": 1.0,
             "sesquihydrate": 1.5, "dihydrate": 2.0, "trihydrate": 3.0,
             "tetrahydrate": 4.0, "pentahydrate": 5.0}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_salt_map() -> list[dict]:
    with SALT_MAP.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def review_rows() -> list[dict]:
    """68 行逐行复核：salt_map 原值 vs 复核后的 (n_base, increment_mw)。"""
    old: dict[str, dict] = {}
    with OLD_CSV.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            old[r["salt_code"]] = r
    out = []
    for r in load_salt_map():
        code = r["salt_code"]
        rule = RULES.get(code)
        o = old.get(code)
        old_n = int(float(o["n_base"])) if o and (o.get("n_base") or "").strip() else None
        try:
            old_delta = float(o["increment_mw"]) if o and (o.get("increment_mw") or "").strip() else None
        except ValueError:
            old_delta = None
        out.append({
            "salt_code": code,
            "salt_en": r["salt_en"],
            "category": r["category"],
            "map_n_counterions": r["n_counterions"],
            "map_counterion_mw": r["counterion_mw"],
            "map_who_inn_hits": r["who_inn_hits"],
            "map_status": r["status"],
            "old_table_n_base": "" if old_n is None else old_n,
            "old_table_increment_mw": "" if old_delta is None else old_delta,
            "review_n_base": rule[0] if rule else "",
            "review_increment_mw": rule[1] if rule else "",
            "review_status": rule[2] if rule else "missing",
            "review_note": rule[3] if rule else "本窗口未复核（不在任何折算规则里）",
            "in_old_40": "yes" if o else "no",
        })
    return out


def write_review_csv(rows: list[dict], path: Path = REVIEW_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return path


def fraction(n_base: int, delta: float, base_mw: float, k: float = 0.0) -> float:
    denom = n_base * base_mw + delta + k * WATER
    return n_base * base_mw / denom


def scan(db) -> tuple[list[dict], dict]:
    """只读扫描 → (候选清单, 统计)。"""
    counts: dict[str, int] = {}
    rows: list[dict] = []
    sql = ("SELECT variant_id, substance_id, salt, salt_code, hydrate, strength_basis,"
           " base_fraction FROM variant WHERE salt_code NOT IN ('', 'non_salt', 'mixed')"
           " ORDER BY variant_id")
    for r in db.execute(sql):
        code = r["salt_code"]
        rule = RULES.get(code)
        n_comp = db.execute("SELECT COUNT(*) FROM product_component WHERE variant_id=?",
                            (r["variant_id"],)).fetchone()[0]
        row = {"variant_id": r["variant_id"], "substance_id": r["substance_id"],
               "salt_code": code, "hydrate": r["hydrate"] or "",
               "old_base_fraction": r["base_fraction"],
               "old_strength_basis": r["strength_basis"],
               "n_components": n_comp, "n_base": "", "increment_mw": "",
               "k_water": "", "base_mw": "", "new_base_fraction": "",
               "new_strength_basis": "", "decision": "", "reason": ""}
        if rule is None:
            row["decision"], row["reason"] = "skip", "salt_code 不在复核表里"
            counts["skip_no_rule"] = counts.get("skip_no_rule", 0) + 1
            rows.append(row)
            continue
        if rule[2] != "usable":
            row["decision"], row["reason"] = "skip", f"复核 status={rule[2]}：{rule[3]}"
            counts[f"skip_{rule[2]}"] = counts.get(f"skip_{rule[2]}", 0) + 1
            rows.append(row)
            continue
        if r["substance_id"] not in BASE_MW:
            row["decision"], row["reason"] = "skip", "碱基分子量未知（BASE_MW 未覆盖）"
            counts["skip_no_base_mw"] = counts.get("skip_no_base_mw", 0) + 1
            rows.append(row)
            continue
        if r["base_fraction"] != 1.0:
            row["decision"], row["reason"] = "skip", "base_fraction 已有非默认值，不覆盖"
            counts["skip_already_set"] = counts.get("skip_already_set", 0) + 1
            rows.append(row)
            continue
        k = HYDRATE_K.get(row["hydrate"])
        if k is None:
            row["decision"], row["reason"] = "skip", f"水合物写法未知：{row['hydrate']}"
            counts["skip_hydrate_parse"] = counts.get("skip_hydrate_parse", 0) + 1
            rows.append(row)
            continue
        mw = BASE_MW[r["substance_id"]][0]
        f = round(fraction(rule[0], rule[1], mw, k), 4)
        row.update({"n_base": rule[0], "increment_mw": rule[1], "k_water": k,
                    "base_mw": mw, "new_base_fraction": f, "new_strength_basis": "salt",
                    "decision": "fill",
                    "reason": f"{BASE_MW[r['substance_id']][1]}；Δ={rule[1]}；{rule[3]}"})
        counts["fill_variants"] = counts.get("fill_variants", 0) + 1
        counts["fill_components"] = counts.get("fill_components", 0) + n_comp
        rows.append(row)
    return rows, counts


def apply(db, rows: list[dict]) -> int:
    todo = [r for r in rows if r["decision"] == "fill"]
    db.execute("BEGIN IMMEDIATE")
    try:
        for r in todo:
            cur = db.execute("UPDATE variant SET base_fraction=?, strength_basis=?"
                             " WHERE variant_id=? AND base_fraction=1.0",
                             (r["new_base_fraction"], r["new_strength_basis"],
                              r["variant_id"])).rowcount
            if cur != 1:
                raise RuntimeError(f"{r['variant_id']} 更新行数 {cur}≠1，回滚本事务")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return len(todo)


def rollback(db, manifest: dict) -> int:
    n = 0
    db.execute("BEGIN IMMEDIATE")
    try:
        for r in manifest["rows"]:
            if r.get("decision") != "fill":
                continue
            n += db.execute(
                "UPDATE variant SET base_fraction=?, strength_basis=? WHERE variant_id=?"
                " AND base_fraction=?", (r["old_base_fraction"], r["old_strength_basis"],
                                         r["variant_id"], r["new_base_fraction"])).rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--review", action="store_true", help="打印/落 68 行复核表（只读）")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    ap.add_argument("--allow-real", action="store_true")
    args = ap.parse_args(argv)

    if args.review:
        rows = review_rows()
        path = write_review_csv(rows)
        miss = [r["salt_code"] for r in rows if r["review_status"] == "missing"]
        print(f"68 行复核表 -> {path}")
        print(f"  usable={sum(1 for r in rows if r['review_status'] == 'usable')}"
              f" note={sum(1 for r in rows if r['review_status'] == 'note')}"
              f" exclude={sum(1 for r in rows if r['review_status'] == 'exclude')}"
              f" missing={len(miss)} {miss}")
        return 0

    action = "rollback" if args.rollback else ("apply" if args.apply else "dry")
    if action in ("apply", "rollback"):
        guard_real(args.db, DEFAULT_DB, action, args.allow_real)
    db = connect(args.db, write=action != "dry")
    try:
        if action == "rollback":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            n = rollback(db, manifest)
            print(f"=== Q3 盐基表回滚 {args.db}：还原 {n} 个 variant ===")
            print("  base_fraction<>1.0:", db.execute(
                "SELECT COUNT(*) FROM variant WHERE base_fraction<>1.0").fetchone()[0])
            print("  strength_basis<>'unknown':", db.execute(
                "SELECT COUNT(*) FROM variant WHERE strength_basis<>'unknown'").fetchone()[0])
            return 0

        rows, counts = scan(db)
        print(f"=== Q3 盐基表回填（{action}）{args.db} ===")
        print("  variant 扫描:", json.dumps(counts, ensure_ascii=False))
        print("  碱基分子量覆盖的物质数:", len(BASE_MW))
        if action != "apply":
            for r in rows:
                if r["decision"] == "fill":
                    print(f"   fill {r['variant_id']:40} {r['salt_code']:14}"
                          f" f={r['new_base_fraction']} comps={r['n_components']}")
            return 0

        before = {"base_fraction_ne_1": db.execute(
            "SELECT COUNT(*) FROM variant WHERE base_fraction<>1.0").fetchone()[0],
            "strength_basis_ne_unknown": db.execute(
                "SELECT COUNT(*) FROM variant WHERE strength_basis<>'unknown'").fetchone()[0]}
        n = apply(db, rows)
        after = {"base_fraction_ne_1": db.execute(
            "SELECT COUNT(*) FROM variant WHERE base_fraction<>1.0").fetchone()[0],
            "strength_basis_ne_unknown": db.execute(
                "SELECT COUNT(*) FROM variant WHERE strength_basis<>'unknown'").fetchone()[0]}
        manifest = {
            "tool": "db/q3_apply_salt_map.py", "db": str(args.db),
            "db_bytes": args.db.stat().st_size,
            "sha256_before": sha256_file(args.db), "created_at": now(),
            "action": "salt_fraction_backfill",
            "salt_map": str(SALT_MAP.relative_to(ROOT)),
            "review_csv": str(REVIEW_CSV.relative_to(ROOT)),
            "rules_usable": sum(1 for v in RULES.values() if v[2] == "usable"),
            "counts": counts, "before": before, "after": after, "rows": rows,
        }
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        print(f"  已写 {n} 个 variant；before={before} after={after}")
        print(f"  manifest: {args.manifest}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
