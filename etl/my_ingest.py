# -*- coding: utf-8 -*-
"""兼容入口：task-7 约定的 `etl/my_ingest.py`。

实现放在 `etl/markets/my.py`（与 CZ / LV / JP / NL 的市场 ingester 同目录、共用
`_ingest_common`）。本文件只做转发，避免同一套写库逻辑出现两份、日后漂移。

    python etl/my_ingest.py --fetch
    python etl/my_ingest.py --dry-run
    python etl/my_ingest.py --apply --db .tmp/my_dryrun.db
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "etl" / "markets"))

from markets.my import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
