"""v0.11.9 渲染探针：只渲染 T18/T21/T26/T28 涉及的页面到 .tmp（不跑全量构建）。

用法（仓库根）：
  $py reports/2026-11-15-t18-t21-render.py .tmp/v0119-after
  $env:T21_OLD='1'; $py reports/2026-11-15-t18-t21-render.py .tmp/v0119-before   # 关掉 H6 徽标
  $env:T21_OLD='0'

渲染内容：
  · combo/  5 个复方页（含工单里的 ferric-oxide-red+pramoxine+zinc-oxide）
  · drug/   2 个成分页（注射剂 / 液体制剂，含「未注明每 mL／每单位基准」的规格）
  · name/   1 个名字页（lyrica：单成分卡，旧版本没有页面级提示）
  · about.html（nickname 口径拆分）
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMBO_TARGETS = [
    "ferric-oxide-red+pramoxine+zinc-oxide.html",
    "allantoin+dimethicone.html",
    "acetaminophen+dextromethorphan+diphenhydramine+phenylephrine.html",
    "aluminum-hydroxide+calcium-carbonate+magnesium-carbonate.html",
    "amlodipine+ramipril.html",
]
DRUG_TARGETS = [s for s in os.environ.get("V0119_DRUGS", "insulin-glargine,amoxicillin").split(",") if s]
NAME_TARGETS = ["lyrica"]


def load_build():
    spec = importlib.util.spec_from_file_location("v0119_build", ROOT / "site" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    out = ROOT / (sys.argv[1] if len(sys.argv) > 1 else ".tmp/v0119-after")
    out.mkdir(parents=True, exist_ok=True)
    mod = load_build()
    if os.environ.get("T21_OLD") == "1":
        mod._form_chip_key = lambda _f: "other"      # 回到 H6 之前：不标「基准未注明」
        print("  [T21_OLD=1] 已关闭 H6 徽标 / 页面说明 / 对照排除")
    if os.environ.get("V0119_FORCE_MATRIX") == "1":
        # 并排对照表（?view=table）只在 multi_ratio ≥ 0.40 的页面上出现；为了验证 H6 在
        # 对照表里的「无法比较」标记，这里把 ratio 抬到 1.0（只影响 evidence 渲染）。
        _orig_list = mod._drug_list_html

        def _force_matrix(*a, **kw):
            html, _ratio, lf = _orig_list(*a, **kw)
            return html, 1.0, lf

        mod._drug_list_html = _force_matrix
        print("  [V0119_FORCE_MATRIX=1] 强制渲染并排对照表")
    mod.OUT = out
    mod.BUILD_V = mod._compute_build_v()
    mod.MAKERS = {}
    db = sqlite3.connect(f"file:{ROOT / 'data' / 'drugs.db'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    mod.SUB_NAME_LANG.clear()
    for sid, nl in db.execute("SELECT substance_id, name_lang FROM substance"):
        mod.SUB_NAME_LANG[sid] = nl or ""
    mod.load_substance_zh(db)
    mod.DRUG_PAGE_IDS.update(r[0] for r in db.execute("SELECT substance_id FROM substance"))

    # ── 索引条目（真实 load_index 的字段，只算渲染需要的部分）
    coll = {r[0]: r[1] for r in db.execute("SELECT key_id, level FROM collision")}
    displays: dict[str, str] = {}
    variants: dict[str, list[str]] = {}
    for key_id, raw in db.execute("SELECT key_id, raw FROM name_variant ORDER BY key_id, v_id"):
        displays.setdefault(key_id, raw)
        variants.setdefault(key_id, []).append(raw)
    prods: dict[str, dict] = defaultdict(lambda: {"sids": set(), "mk": set(), "mah": set(),
                                                  "s": set()})
    _base_of, _ = mod._sub_base_map(db)
    for (pid, sid, mk, mah, sv, su, pv, pu) in db.execute(
            """SELECT p.product_id, v.substance_id, COALESCE(p.country, p.region), p.mah,
                      pc.strength_value, pc.strength_unit, pc.per_volume_value,
                      pc.per_volume_unit
               FROM product p
               JOIN product_component pc ON pc.product_id = p.product_id
               LEFT JOIN variant v ON v.variant_id = pc.variant_id"""):
        rec = prods[pid]
        if sid:
            rec["sids"].add(_base_of.get(sid, sid))   # 与检索索引同一套盐型归并口径
        rec["mk"].add(mk)
        if mah:
            rec["mah"].add(mah)
        st = mod._spec_text(sv, su, pv, pu)
        if st:
            rec["s"].add(st)
    key_pids: dict[str, set[str]] = defaultdict(set)
    for pid, key_id in db.execute(
            "SELECT product_id, key_id FROM product_name WHERE name_type = 'trade'"):
        if pid in prods:
            key_pids[key_id].add(pid)

    def entry_for(key: str) -> dict:
        pids = key_pids.get(key) or set()
        sids: set[str] = set()
        mks: set[str] = set()
        mahs: set[str] = set()
        specs: set[str] = set()
        for pid in pids:
            sids |= prods[pid]["sids"]
            mks |= prods[pid]["mk"]
            mahs |= prods[pid]["mah"]
            specs |= prods[pid]["s"]
        return {"k": key, "d": displays.get(key, key), "u": mod.key_file(key),
                "n": len(pids), "t": 1, "l": coll.get(key, "info"), "c": sorted(mks),
                "vs": sorted(sids) if len(sids) > 1 else None,
                "s": sorted(specs, key=lambda s: (mod._sort_strength(s), s))[:6],
                "m": sorted(mahs)[0] if mahs else ""}

    entries = [entry_for(k) for k in key_pids]

    # i18n（About 的统计占位符用真实库值）
    stats = {
        "products": db.execute("SELECT COUNT(*) FROM product").fetchone()[0],
        "substances": db.execute("SELECT COUNT(*) FROM substance").fetchone()[0],
        "atc": db.execute("SELECT COUNT(*) FROM substance WHERE atc IS NOT NULL AND atc <> ''"
                          ).fetchone()[0],
        "keys": db.execute("SELECT COUNT(*) FROM name_key").fetchone()[0],
        "aliases": db.execute("SELECT COUNT(*) FROM alias_all").fetchone()[0],
        "confusable": db.execute("SELECT COUNT(*) FROM confusable_pair").fetchone()[0],
        "severe": db.execute("SELECT COUNT(*) FROM collision WHERE level='severe'"
                             ).fetchone()[0],
    }
    _nick_total = db.execute("SELECT COUNT(*) FROM nickname").fetchone()[0]
    _nick_merged = db.execute(
        "SELECT COUNT(*) FROM nickname WHERE source LIKE 'T17%'").fetchone()[0]
    stats["nickname"] = _nick_total - _nick_merged
    stats["nickname_total"] = _nick_total
    stats["nickname_merged"] = _nick_merged
    stats["atc_pct"] = round(stats["atc"] / stats["substances"] * 100, 1)
    stats["drug_term"] = db.execute("SELECT COUNT(*) FROM drug_term").fetchone()[0]
    for k in ("high", "medium", "info"):
        stats[f"warn_{k}"] = 0
    stats["warn_total"] = 0
    coverage = [dict(r) for r in db.execute("SELECT * FROM coverage ORDER BY country")]
    source_cover = [dict(r) for r in db.execute(
        """SELECT COALESCE(p.country, p.region) AS country, p.source_id,
                  COUNT(DISTINCT p.product_id) AS n_products, s.data_as_of, s.data_as_of_note
           FROM product p LEFT JOIN source s ON s.source_id = p.source_id
           GROUP BY country, p.source_id ORDER BY country, n_products DESC""")]
    values = mod._i18n_placeholders(stats, mod._atc_coverage(db), coverage, source_cover)
    mod._merge_static_i18n(values)
    mod._install_zh_hant(values)
    print(f"  nickname: total {_nick_total} / curated {stats['nickname']} / "
          f"merged {_nick_merged}")

    # ── 复方页：只渲染目标 slug（only_slugs 是本次新增的测试钩子，默认 None = 全站）
    wanted = set(COMBO_TARGETS)
    slugs: dict[str, tuple] = {}
    for e in entries:
        vs = e.get("vs")
        if vs and len(vs) >= 2:
            sl = mod.combo_slug(tuple(sorted(vs)))
            if sl in wanted:
                slugs[sl] = tuple(sorted(vs))
    mod.COMBO_PAGE_SLUGS.clear()
    mod.COMBO_PAGE_SLUGS.update(wanted)
    n_combo = mod.build_combo_pages(entries, db, only_slugs=wanted)
    print(f"  combo pages rendered: {n_combo} (targets found: {sorted(slugs)})")

    # ── 成分页：只渲染指定成分
    n_drug = mod.build_drug_pages(db, entries, only_sids=set(DRUG_TARGETS))
    print(f"  drug pages rendered: {n_drug}")

    # ── 名字页
    data = mod.collect_name_data(db)
    families: dict[str, dict] = {}
    members: dict[str, list[str]] = defaultdict(list)
    for key_id, fam_id, label, note in db.execute(
            "SELECT nf.key_id, bf.family_id, bf.label, bf.note FROM name_family nf"
            " JOIN brand_family bf ON bf.family_id = nf.family_id"):
        families[key_id] = {"id": fam_id, "label": label, "note": note, "members": []}
        members[fam_id].append(key_id)
    for fam in families.values():
        fam["members"] = members[fam["id"]]
    name_entries = [entry_for(k) for k in NAME_TARGETS if k in key_pids]
    n_name = mod.build_name_pages(db, name_entries, data, families,
                                  {e["k"]: e["d"] for e in name_entries})
    print(f"  name pages rendered: {n_name}")

    # ── About
    mod.build_about(stats, coverage, source_cover)
    print(f"  about.html rendered: {(out / 'about.html').stat().st_size:,} B")
    for d in ("combo", "drug", "name"):
        p = out / d
        if p.exists():
            print(f"  {d}/: {sum(1 for _ in p.iterdir())} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
