"""ATC4 类目「成分 × 剂型 × 市场」事实表生成（只读，task-145 数据侧）。

产物：`data/sources/atc4_forms_20261031.json`
结构：{ "generated_at": ..., "rows": [[atc4, substance_id, form_base, country, products], ...] }
用途：v0.9.6 的 ATC4 类目页「按剂型看跨市场明细」按需渲染（客户端读 JSON），
      或未来转成静态表（受 900 MiB 体积预算约束，见 reports/task146-size-budget-20261031.md）。

边界：只读 `mode=ro`；只列事实，不排序推荐、不做替代判断、不改库。

用法：
    & $py db/atc4_forms.py
    & $py db/atc4_forms.py --out .tmp/atc4.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "drugs.db"
DEFAULT_OUT = ROOT / "data" / "sources" / "atc4_forms_20261031.json"

# 非药品/剂型缺失的 form_base 不进表
SKIP_FORMS = {"unknown", ""}
# 剂型归一：form_base 有 876 个取值（AU 导出夹带自由文本），只保留覆盖 99%+ 的前 N 个，
# 其余一律归 "other"（不丢行，只并类）。
KEEP_FORMS_DEFAULT = 30


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 ATC4 成分×剂型×市场事实表（只读）")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--keep-forms", type=int, default=KEEP_FORMS_DEFAULT, help="保留的剂型种类数，其余归 other")
    args = ap.parse_args()

    if not DB.exists():
        print(f"[FAIL] 找不到库：{DB}")
        return 1
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    keep = {
        f for f, _n in con.execute(
            "SELECT form_base, COUNT(*) n FROM product WHERE form_base IS NOT NULL "
            "GROUP BY 1 ORDER BY n DESC LIMIT ?", (args.keep_forms,)
        )
    }
    rows = con.execute(
        """
        SELECT substr(s.atc, 1, 5) AS atc4,
               v.substance_id,
               p.form_base,
               p.country,
               COUNT(DISTINCT p.product_id) AS n
        FROM product p
        JOIN product_component pc ON pc.product_id = p.product_id
        JOIN variant v            ON v.variant_id = pc.variant_id
        JOIN substance s          ON s.substance_id = v.substance_id
        WHERE s.atc IS NOT NULL AND length(s.atc) >= 5
        GROUP BY 1, 2, 3, 4
        HAVING n > 0
        ORDER BY 1, 2, 3, 4
        """
    ).fetchall()

    agg: dict[tuple[str, str, str, str], int] = {}
    for atc4, sid, form, country, n in rows:
        if form in SKIP_FORMS:
            continue
        key = (atc4, sid, form if form in keep else "other", country)
        agg[key] = agg.get(key, 0) + n

    payload = {
        "generated_at": date.today().isoformat(),
        "note": "ATC4 x substance x form x country product counts; facts only, not a recommendation.",
        "rows": [[atc4, sid, form, country, n] for (atc4, sid, form, country), n in sorted(agg.items())],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    classes = {r[0] for r in payload["rows"]}
    substances = {r[1] for r in payload["rows"]}
    forms = {r[2] for r in payload["rows"]}
    markets = {r[3] for r in payload["rows"]}
    size = out.stat().st_size
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"rows      : {len(payload['rows']):,}")
    print(f"ATC4      : {len(classes):,}  成分: {len(substances):,}  剂型: {len(forms)}  市场: {len(markets)}")
    print(f"bytes     : {size:,} B（{size / 1024**2:.2f} MiB）")
    print(f"out       : {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
