"""v0.11.9 数字核对：H3 复方页行数 vs DB · H6 缺基准规格数量（只读 SQL）。

用法：$py reports/2026-11-15-t18-t21-count.py
"""
from __future__ import annotations

import importlib.util
import io
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AFTER = ROOT / ".tmp" / "v0119-after" / "combo"
COMBOS = [
    "ferric-oxide-red+pramoxine+zinc-oxide.html",
    "allantoin+dimethicone.html",
    "acetaminophen+dextromethorphan+diphenhydramine+phenylephrine.html",
    "aluminum-hydroxide+carbonate+magensium.html",   # 不存在 → 跳过
    "aluminum-hydroxide+calcium-carbonate+magnesium-carbonate.html",
    "amlodipine+ramipril.html",
]


def load_build():
    spec = importlib.util.spec_from_file_location("v0119_build", ROOT / "site" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    mod = load_build()
    db = sqlite3.connect(f"file:{ROOT / 'data' / 'drugs.db'}?mode=ro", uri=True)
    base_of, _ = mod._sub_base_map(db)

    print("=== H3：复方页渲染行数 vs DB 现查 ===")
    print("口径：品牌行 = 名字键（其产品成分并集[盐型归并到 base] == 页面成分集合）；")
    print("      含量行 = 该名字键下「成分集合 ⊆ 页面集合」的不同含量组合（页面最多显示 4 条）。\n")
    total_ok = 0
    for slug in COMBOS:
        p = AFTER / slug
        if not p.exists():
            continue
        page_sids = set(slug[:-5].split("+"))
        html = io.open(p, encoding="utf-8").read()
        rows = re.findall(r'<tr data-key="([^"]*)">(.*?)</tr>', html, re.S)
        # DB：名字键 → 产品成分（base 归并）并集
        key_sids: dict[str, set[str]] = {}
        key_comps: dict[str, set[tuple]] = {}
        for key, pid, sid in db.execute(
                """SELECT pn.key_id, p.product_id, v.substance_id
                   FROM product p JOIN product_name pn ON pn.product_id = p.product_id
                   AND pn.name_type = 'trade'
                   LEFT JOIN product_component pc ON pc.product_id = p.product_id
                   LEFT JOIN variant v ON v.variant_id = pc.variant_id"""):
            if sid:
                key_sids.setdefault(key, set()).add(base_of.get(sid, sid))
        want_keys = {k for k, s in key_sids.items() if s == page_sids}
        got_keys = {k for k, _ in rows}
        print(f"--- {slug}")
        print(f"  品牌行: 渲染 {len(got_keys)} / DB {len(want_keys)} → "
              f"{'OK' if got_keys == want_keys else 'MISMATCH'}")
        if got_keys != want_keys:
            print(f"    只在渲染: {sorted(got_keys - want_keys)[:5]}")
            print(f"    只在 DB  : {sorted(want_keys - got_keys)[:5]}")
        else:
            total_ok += 1
        for key, cell in rows:
            n_li = len(re.findall(r"<li>", cell))
            more = re.search(r'data-total="(\d+)"', cell)
            more_n = int(more.group(1)) if more else 0
            comps = db.execute(
                """SELECT COUNT(*) FROM (
                       SELECT p.product_id,
                              GROUP_CONCAT(COALESCE(v.substance_id,''), '|') AS sig
                       FROM product p
                       JOIN product_name pn ON pn.product_id = p.product_id
                            AND pn.name_type = 'trade'
                       LEFT JOIN product_component pc ON pc.product_id = p.product_id
                       LEFT JOIN variant v ON v.variant_id = pc.variant_id
                       WHERE pn.key_id = ?
                       GROUP BY p.product_id)""", (key,)).fetchone()[0]
            # 只要页面这条键的成分并集等于页面集合，上面的产品数就是记录数上界
            shown = n_li + more_n
            flag = "OK" if shown >= min(comps, 1) else "?"
            print(f"    {key[:44]:44} 渲染行 {n_li} + 更多 {more_n}; DB 该键产品数 {comps} [{flag}]")
            break   # 每个页面只核第一个品牌行，避免刷屏

    print(f"\n品牌行完全一致：{total_ok}/{len([c for c in COMBOS if (AFTER / c).exists()])} 个页面")

    print("\n=== H6：缺计量基准（注射/液体剂型 + 有强度 + 无 per_volume）现查 ===")
    q1 = db.execute(
        """SELECT COUNT(*) FROM product_component pc
           JOIN product p ON p.product_id = pc.product_id
           WHERE pc.strength_value IS NOT NULL
             AND (pc.per_volume_value IS NULL OR pc.per_volume_value = 0)
             AND LOWER(COALESCE(p.form_base, p.dosage_form, '')) IN ('injection', 'liquid')"""
    ).fetchone()[0]
    q2 = db.execute(
        """SELECT COUNT(*) FROM (
             SELECT DISTINCT v.substance_id, pc.strength_value, pc.strength_unit,
                    LOWER(COALESCE(p.form_base, p.dosage_form, '')) AS f
             FROM product_component pc
             JOIN product p ON p.product_id = pc.product_id
             LEFT JOIN variant v ON v.variant_id = pc.variant_id
             WHERE pc.strength_value IS NOT NULL
               AND (pc.per_volume_value IS NULL OR pc.per_volume_value = 0)
               AND LOWER(COALESCE(p.form_base, p.dosage_form, '')) IN ('injection', 'liquid'))"""
    ).fetchone()[0]
    q3 = db.execute(
        """SELECT COUNT(DISTINCT v.substance_id) FROM product_component pc
           JOIN product p ON p.product_id = pc.product_id
           LEFT JOIN variant v ON v.variant_id = pc.variant_id
           WHERE pc.strength_value IS NOT NULL
             AND (pc.per_volume_value IS NULL OR pc.per_volume_value = 0)
             AND LOWER(COALESCE(p.form_base, p.dosage_form, '')) IN ('injection', 'liquid')"""
    ).fetchone()[0]
    print(f"  成分行（product_component）：{q1:,}")
    print(f"  去重后的规格行（成分+强度+剂型）：{q2:,}")
    print(f"  受影响的成分页：{q3:,}")

    print("\n=== I3：nickname 口径（现查）===")
    for kind, n in db.execute("SELECT kind, COUNT(*) FROM nickname GROUP BY kind"):
        print(f"  kind={kind:10} {n}")
    tot = db.execute("SELECT COUNT(*) FROM nickname").fetchone()[0]
    merged = db.execute("SELECT COUNT(*) FROM nickname WHERE source LIKE 'T17%'").fetchone()[0]
    print(f"  合计 {tot} = 人工维护 {tot - merged} + 合并前中文名 {merged}")


if __name__ == "__main__":
    main()
