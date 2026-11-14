"""T16 计数探针（只读）：品牌页「释放方式结论」受影响面 before / after。

口径：
  · 名字页的「释放方式结论」= 两条来源
      ① 品牌对照表「关系说明」列的 fam.rel.release 行（_family_relation 推导）
      ② 名字页顶部警示条 name.warning（collision.level = 'warning'）
  · 本脚本统计两者在全部名字页上的行数 / 页数，供报告前后对比。

用法：
  $py .tmp/t16-count.py            # 打印 JSON
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_build():
    spec = importlib.util.spec_from_file_location("t16_build", ROOT / "site" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    build = load_build()
    db = sqlite3.connect(f"file:{ROOT / 'data' / 'drugs.db'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row

    out: dict = {}

    # ── SQL 基线（可复核）：trade name key 里 release 有多种的 key 数
    out["sql_multi_release_trade_keys"] = db.execute(
        """SELECT COUNT(*) FROM (
               SELECT pn.key_id
               FROM product_name pn JOIN product p ON p.product_id = pn.product_id
               WHERE pn.name_type = 'trade'
               GROUP BY pn.key_id
               HAVING COUNT(DISTINCT p.release) > 1)""").fetchone()[0]
    out["sql_collision_warning_keys"] = db.execute(
        "SELECT COUNT(*) FROM collision WHERE level = 'warning'").fetchone()[0]
    out["sql_collision_severe_keys"] = db.execute(
        "SELECT COUNT(*) FROM collision WHERE level = 'severe'").fetchone()[0]

    # ── 名字页数据（与 main() 同一份）
    data = build.collect_name_data(db)
    families: dict[str, dict] = {}
    members: dict[str, list[str]] = {}
    for key_id, fam_id in db.execute("SELECT key_id, family_id FROM name_family"):
        families[key_id] = {"id": fam_id}
        members.setdefault(fam_id, []).append(key_id)
    for key_id, fam in families.items():
        fam["members"] = members["%s" % fam["id"]]

    # ── ① 品牌对照表：关系列逐行统计（页 × 成员）
    rel_counter: Counter[str] = Counter()
    multi_rel_rows = 0
    rel_rows_total = 0
    pages_with_multi_rel_row: set[str] = set()
    for key in sorted(families):
        cur = build._key_subs(data, key)
        for member in families[key]["members"]:
            rel_rows_total += 1
            rel_key = build._family_relation(cur, build._key_subs(data, member))
            rel_counter[rel_key] += 1
            if rel_key in ("fam.rel.release", "fam.rel.multi"):
                a = build._key_releases(cur)
                b = build._key_releases(build._key_subs(data, member))
                if len(a) > 1 or len(b) > 1:
                    multi_rel_rows += 1
                    pages_with_multi_rel_row.add(key)
    out["family_pages"] = len(families)
    out["family_rows_total"] = rel_rows_total
    out["family_rel_keys"] = dict(sorted(rel_counter.items()))
    out["family_multi_rel_rows"] = multi_rel_rows
    out["family_pages_with_multi_rel_row"] = len(pages_with_multi_rel_row)

    # ── ② 顶部警示条：collision level 分布（名字页只对 warning/severe 出条）
    lv = Counter(r[0] for r in db.execute("SELECT level FROM collision"))
    out["collision_levels"] = dict(sorted(lv.items()))

    # ── ③ 三个抽样页现查
    samples = {}
    for key in ("tylenol extra strength", "lyrica", "lamictal"):
        subs = build._key_subs(data, key)
        samples[key] = {
            "substances": {sid: sorted((g.get("rel") or set()) - {"none"})
                           for sid, g in subs.items()},
            "family_members": families.get(key, {}).get("members", []),
            "level": (db.execute("SELECT level FROM collision WHERE key_id = ?",
                                 (key,)).fetchone() or ["—"])[0],
        }
    out["samples"] = samples

    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
