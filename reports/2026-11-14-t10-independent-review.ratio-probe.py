# -*- coding: utf-8 -*-
"""T10 独立复核用探针：复算「内嵌并排矩阵」页数（旧 key vs 新 key）。

只读 `data/drugs.db`（`mode=ro`），不写库、不写 dist、不改任何实现文件。
口径尽量与 `site/build.py::build_drug_pages` + `_drug_list_html` 对齐：
  · 状态过滤：active 全收；HK/AU/EU 额外收 unknown/空；
  · 规格串：重量单位 → mg（含 `_snap_strength` 窄口归整）+ per_volume 拼 `/X unit`；
  · 旧 key = (spec, form, release)；新 key = 旧 key + others_sig（除本页成分外的成分签名）；
  · multi_ratio = 「出现在 ≥2 个国家的规格行数 / 该成分全部规格行数」，阈值 0.40。

输出：旧/新各自的内嵌页数、以及「旧有内嵌、新丢失」的成分页清单（前 20 个 + 计数）。

用法（仓库根）：
    & $py reports/2026-11-14-t10-independent-review.ratio-probe.py
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
THRESHOLD = 0.40

_UNIT_TO_MG = {
    "g": 1000.0, "kg": 1000000.0,
    "mcg": 0.001, "ug": 0.001, "μg": 0.001, "µg": 0.001,
    "microgram": 0.001, "micrograms": 0.001, "ng": 0.000001,
}


def _fmt(x: float) -> str:
    s = format(x, ",.6f").rstrip("0").rstrip(".")
    return s or "0"


def _snap(v: float) -> float:
    """与 site/build.py::_snap_strength 同一条窄口规则。"""
    if v is None or v < 1:
        return v
    r = float(round(v))
    dev = abs(v - r)
    if dev <= 0.01 and dev <= 2e-05 * r:
        return r
    return v


def _normalized(v, u) -> str:
    if v is None:
        return ""
    u = (u or "").strip()
    factor = _UNIT_TO_MG.get(u.lower())
    if factor is not None:
        num = float(v) * factor
        if num <= 100000:
            return _fmt(_snap(num)) + " mg"
        return (_fmt(float(v)) + " " + u).strip()
    num = float(v)
    snapped = _snap(num)
    if snapped != num:
        return (_fmt(snapped) + " " + u).strip()
    return (_fmt(float(v)) + " " + u).strip()


def _spec_text(sv, su, pv, pu) -> str:
    s = _normalized(sv, su)
    if s and pv is not None:
        s += "/" + _fmt(float(pv)) + " " + (pu or "").strip()
        s = s.rstrip()
    return s


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # 1) 每个产品的成分签名（含各自含量串），供 others_sig 与「单方/复方」判定
    comps: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in conn.execute(
            """SELECT pc.product_id AS pid, v.substance_id AS sid,
                      pc.strength_value AS sv, pc.strength_unit AS su,
                      pc.per_volume_value AS pv, pc.per_volume_unit AS pu,
                      pc.ord AS ord
               FROM product_component pc
               JOIN variant v ON v.variant_id = pc.variant_id
               ORDER BY pc.product_id, pc.ord"""):
        comps[r["pid"]].append((r["sid"], _spec_text(r["sv"], r["su"], r["pv"], r["pu"])))

    # 2) 成分页数据行（与 build_drug_pages 同一状态过滤）
    rows = conn.execute(
        """SELECT v.substance_id AS sid, p.product_id AS pid,
                  COALESCE(p.country, p.region) AS mk,
                  p.form_base AS fb, p.dosage_form AS df, p.release AS rel,
                  p.status AS status,
                  pc.strength_value AS sv, pc.strength_unit AS su,
                  pc.per_volume_value AS pv, pc.per_volume_unit AS pu
           FROM product p
           JOIN product_component pc ON pc.product_id = p.product_id
           JOIN variant v ON v.variant_id = pc.variant_id""").fetchall()

    old_specs: dict[str, set] = defaultdict(set)          # sid → {(spec, form, rel)}
    new_specs: dict[str, set] = defaultdict(set)          # sid → {..., others_sig}
    old_where: dict[tuple, set] = defaultdict(set)        # (sid, spec) → markets
    new_where: dict[tuple, set] = defaultdict(set)
    for r in rows:
        st = _spec_text(r["sv"], r["su"], r["pv"], r["pu"]).strip()
        form = r["fb"] or r["df"] or ""
        rel = r["rel"]
        status, mk = r["status"], r["mk"]
        if status != "active" and not (status in ("unknown", "", None) and mk in ("HK", "AU", "EU")):
            continue
        others = "|".join(f"{cs}@{sx}" for cs, sx in comps.get(r["pid"], []) if cs != r["sid"])
        k_old = (st, form, rel)
        k_new = (st, form, rel, others)
        old_specs[r["sid"]].add(k_old)
        new_specs[r["sid"]].add(k_new)
        old_where[(r["sid"], k_old)].add(mk)
        new_where[(r["sid"], k_new)].add(mk)

    def ratios(specs: dict[str, set], where: dict[tuple, set],
               mono_only: bool = False) -> dict[str, float]:
        out = {}
        for sid, ss in specs.items():
            if mono_only:
                ss = {k for k in ss if not k[3]}
                if not ss:
                    continue
            if not ss:
                continue
            multi = sum(1 for k in ss if len(where.get((sid, k), ())) >= 2)
            out[sid] = multi / len(ss)
        return out

    old_ratio = ratios(old_specs, old_where)
    new_ratio = ratios(new_specs, new_where)
    # 对照方案：阈值只看单方行（复方单独成段，不该把它挤掉矩阵），但仍渲染全部行
    new_ratio_mono = ratios(new_specs, new_where, mono_only=True)

    old_pages = {s for s, v in old_ratio.items() if v >= THRESHOLD}
    new_pages = {s for s, v in new_ratio.items() if v >= THRESHOLD}
    lost = sorted(old_pages - new_pages)

    name = {r["substance_id"]: (r["inn_en"] or r["substance_id"])
            for r in conn.execute("SELECT substance_id, inn_en FROM substance")}

    print(f"成分页总数（有行的成分）: {len(old_ratio)}")
    print(f"旧 key 内嵌矩阵页 (ratio>=0.40): {len(old_pages)}")
    print(f"新 key 内嵌矩阵页 (ratio>=0.40): {len(new_pages)}")
    print(f"丢失页数: {len(lost)}  新增页数: {len(new_pages - old_pages)}")
    mono_pages = {s for s, v in new_ratio_mono.items() if v >= THRESHOLD}
    print(f"[对照] 只按单方行算 ratio 的内嵌页数: {len(mono_pages)} "
          f"(与旧 key 的重合 {len(mono_pages & old_pages)} / 旧 {len(old_pages)})")
    print()
    print("丢失页明细（前 20，按旧 ratio 降序）：")
    for sid in sorted(lost, key=lambda s: -old_ratio[s])[:20]:
        print(f"  {sid:38s} {name.get(sid,''):28s} "
              f"old={old_ratio[sid]:.3f} new={new_ratio[sid]:.3f} "
              f"specs_old={len(old_specs[sid])} specs_new={len(new_specs[sid])}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
