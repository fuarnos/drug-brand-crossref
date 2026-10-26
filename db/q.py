"""临时查询：python db/q.py "SELECT ..." """

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "drugs.db"


def main() -> None:
    sql = sys.argv[1] if len(sys.argv) > 1 else "SELECT 1"
    db = sqlite3.connect(DB)
    cur = db.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    if cols:
        print(" | ".join(cols))
    for row in cur.fetchall():
        print(" | ".join("" if v is None else str(v) for v in row))
    db.close()


if __name__ == "__main__":
    main()
