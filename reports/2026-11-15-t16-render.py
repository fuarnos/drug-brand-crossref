"""T16 轻量渲染器：只渲染指定的几个名字页到 .tmp/（不跑全量 build.py）。

用法：
  $py .tmp/t16-render.py <build_py> <out_dir> [key1,key2,...]

为什么不用 `site/build.py`：全量构建约 20 分钟 / 1 GB，而 T16 只改名字页模板
（banner + 品牌对照表 + 成分卡），所以这里直接调用 build.py 里的同名函数渲染
3–5 个指定页面，产物结构和真实构建完全一致（同一个 page() / build_name_pages()）。
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEYS = ["tylenol extra strength", "lyrica", "lamictal", "泰诺林", "lyrica-asdf"]


def load_build(path: Path):
    spec = importlib.util.spec_from_file_location("t16_build", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _patch_before(mod) -> None:
    """把 T16 改掉的三个函数换回改动前的实现（同一份源码、同一份数据 → 真实 before DOM）。"""
    def old_key_releases(subs: dict) -> set[str]:
        return {x for g in subs.values() for x in (g.get("rel") or ())
                if x and x != "none"}

    def old_family_relation(cur_subs: dict, sib_subs: dict) -> str:
        a, b = set(cur_subs), set(sib_subs)
        if not a or not b:
            return "fam.rel.none"
        if a == b:
            return ("fam.rel.release" if old_key_releases(cur_subs) != old_key_releases(sib_subs)
                    else "fam.rel.same")
        return "fam.rel.partial" if a & b else "fam.rel.diff"

    def old_rel_html(rel_key: str, *_sides) -> str:
        T = mod.I18N["en"]
        return f'<span data-i18n="{rel_key}">{mod.esc(T[rel_key])}</span>'

    def old_banner(_subs: dict) -> str:
        return ('<div class="notice"><b data-i18n="badge.warning">Different release</b>'
                '<span data-i18n="name.warning"> — not interchangeable.</span></div>')

    mod._key_releases = old_key_releases
    mod._family_relation = old_family_relation
    mod._family_rel_html = old_rel_html
    mod._release_variant_notice = old_banner


def main() -> int:
    build_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site" / "build.py"
    out_dir = ROOT / (sys.argv[2] if len(sys.argv) > 2 else ".tmp/t16-after")
    keys = (sys.argv[3].split(",") if len(sys.argv) > 3 else DEFAULT_KEYS)

    mod = load_build(build_path)
    if os.environ.get("T16_OLD") == "1":
        _patch_before(mod)
        print("  [T16_OLD=1] 已把 _key_releases / _family_relation / _family_rel_html /"
              " _release_variant_notice 换回改动前实现")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "name").mkdir(parents=True, exist_ok=True)
    mod.OUT = out_dir
    mod.BUILD_V = mod._compute_build_v()
    mod._merge_static_i18n({})
    mod._install_zh_hant({})
    mod.MAKERS = {}

    db = sqlite3.connect(f"file:{ROOT / 'data' / 'drugs.db'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    mod.SUB_NAME_LANG.clear()
    for sid, nl in db.execute("SELECT substance_id, name_lang FROM substance"):
        mod.SUB_NAME_LANG[sid] = nl or ""
    mod.load_substance_zh(db)
    mod.DRUG_PAGE_IDS.update(r[0] for r in db.execute("SELECT substance_id FROM substance"))

    coll = {r[0]: r[1] for r in db.execute("SELECT key_id, level FROM collision")}
    displays: dict[str, str] = {}
    variants: dict[str, list[str]] = {}
    for key_id, raw in db.execute("SELECT key_id, raw FROM name_variant ORDER BY key_id, v_id"):
        displays.setdefault(key_id, raw)
        variants.setdefault(key_id, []).append(raw)
    entries = []
    for key in keys:
        row = db.execute(
            """SELECT COUNT(DISTINCT p.product_id) FROM product_name pn
               JOIN product p ON p.product_id = pn.product_id WHERE pn.key_id = ?""",
            (key,)).fetchone()
        if not row or not row[0]:
            print(f"skip (no such key): {key!r}")
            continue
        entries.append({"k": key, "d": displays.get(key, key), "u": mod.key_file(key),
                        "n": row[0], "t": 1, "l": coll.get(key, "info"),
                        "c": sorted({r[0] for r in db.execute(
                            """SELECT COALESCE(p.country, p.region) FROM product_name pn
                               JOIN product p ON p.product_id = pn.product_id
                               WHERE pn.key_id = ?""", (key,))})})
    data = mod.collect_name_data(db)
    families: dict[str, dict] = {}
    members: dict[str, list[str]] = {}
    for key_id, fam_id, label, note in db.execute(
            "SELECT nf.key_id, bf.family_id, bf.label, bf.note FROM name_family nf"
            " JOIN brand_family bf ON bf.family_id = nf.family_id"):
        families[key_id] = {"id": fam_id, "label": label, "note": note, "members": []}
        members.setdefault(fam_id, []).append(key_id)
    for fam in families.values():
        fam["members"] = members[fam["id"]]
    made = mod.build_name_pages(db, entries, data, families,
                                {e["k"]: e["d"] for e in entries})
    print(f"rendered {made} name pages -> {out_dir}")
    for e in entries:
        p = out_dir / "name" / e["u"]
        print(f"  {p}  {p.stat().st_size:,} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
