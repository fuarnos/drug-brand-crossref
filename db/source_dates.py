"""把「数据源自己发布 / 生效 / 快照」的日期写进 source.data_as_of。

覆盖表以前显示 product.retrieved_at（= 我们抓取的时间）。对用户没意义：
中国数据是 2025-04-04 的快照，却显示成 2026-10-26。这个脚本按源分别取值：

    openfda_ndc      openFDA 响应 meta.last_updated（文件头里，不用读 240 MB 全文）
    dmd              dm+d 包名里的发布日期，如 nhsbsa_dmd_10.2.0_20261019000001.zip
    nhsa             快照文件名，如 nhsa_codes_20250404.csv
    pbs              source.notes 里的「生效 YYYY-MM-DD」（PBS schedule effective date）
    cima             实时数据库，没有快照日期 → note='live'
    cofepris_mx      只发布年度 PDF，没有单一日期 → note='annual'
    tga_cmi / artg_* 实时目录，没有快照日期 → note='live'
    hc_dpd           实时数据库；页面上的「上次更新」取所有产品的 last_update_date 最大值

可重复运行，只写 source 表；在 run_all.py 里位于所有 ingest 之后、建站之前。
"""

from __future__ import annotations

import argparse
import glob
import re
import sqlite3
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "drugs.db"


def _iso(y: str, m: str, d: str) -> str | None:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def _openfda_as_of(root: Path) -> str | None:
    path = root / "data" / "raw" / "openfda" / "ndc-01.json"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        head = f.read(8192)
    m = re.search(rb'"last_updated"\s*:\s*"(\d{4}-\d{2}-\d{2})"', head)
    return m.group(1).decode() if m else None


def _newest_named_date(pattern: str, root: Path, re_pattern: str) -> str | None:
    files = sorted(glob.glob(str(root / pattern)))
    if not files:
        return None
    m = re.search(re_pattern, Path(files[-1]).name)
    if not m:
        return None
    return _iso(m.group(1), m.group(2), m.group(3))


def _pbs_as_of(db: sqlite3.Connection) -> str | None:
    row = db.execute("SELECT notes FROM source WHERE source_id='pbs'").fetchone()
    if not row or not row[0]:
        return None
    m = re.search(r"生效\s*(\d{4}-\d{2}-\d{2})", row[0])
    return m.group(1) if m else None


def _dpd_as_of(root: Path) -> str | None:
    """DPD 是实时库；每个产品自带 last_update_date，取最大值当「数据截止」。

    不逐条读 5.8 万行 JSON：DPD 的 JSON 按 drug_code 升序，改过的记录日期很新但位置靠前，
    所以扫全文件取最大值（16 MB，一次几百毫秒，只跑一次）。
    """
    import json

    path = root / "data" / "raw" / "ca" / "dpd" / "drugproduct.json"
    if not path.exists():
        return None
    rows = json.loads(path.read_text(encoding="utf-8"))
    dates = [r.get("last_update_date") for r in rows if r.get("last_update_date")]
    return max(dates) if dates else None


def update(db: sqlite3.Connection) -> list[tuple]:
    # 实时目录 / 年度清单：没有可展示的单一数据日期，交给页面标 live / —
    derived: dict[str, tuple[str | None, str | None]] = {
        "openfda_ndc": (_openfda_as_of(ROOT), None),
        "dmd": (_newest_named_date("data/raw/dmd/nhsbsa_dmd_*.zip", ROOT,
                                   r"_(\d{4})(\d{2})(\d{2})\d*\.zip$"), None),
        "nhsa": (_newest_named_date("data/raw/nhsa/nhsa_codes_*.csv", ROOT,
                                    r"_(\d{4})(\d{2})(\d{2})\.csv$"), None),
        "pbs": (_pbs_as_of(db), None),
        "tga_cmi": (None, "live"),
        "artg_index": (None, "live"),
        "artg_enrich": (None, "live"),
        "artg_detail": (None, "live"),
        "cima": (None, "live"),
        "cofepris_mx": (None, "annual"),
        "hc_dpd": (_dpd_as_of(ROOT), None),
    }
    out = []
    for source_id, (as_of, note) in derived.items():
        cur = db.execute(
            "UPDATE source SET data_as_of=?, data_as_of_note=? WHERE source_id=?",
            (as_of, note, source_id))
        out.append((source_id, as_of, note, cur.rowcount))
    db.commit()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    try:
        for source_id, as_of, note, n in update(db):
            if n:
                print(f"  {source_id:14} {as_of or '(none)':12} {note or ''}")
            else:
                print(f"  {source_id:14} skipped (source row not found)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
