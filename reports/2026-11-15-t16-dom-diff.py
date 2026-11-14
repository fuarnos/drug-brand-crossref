"""T16 DOM 证据：before/after 名字页片段对照（同一份源码 + 同一数据库，只切回/启用 T16 逻辑）。"""
from __future__ import annotations

import difflib
import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["tylenol-extra-strength", "lyrica", "lamictal", "depakote"]


def fragments(html: str) -> dict:
    out = {
        "notice": [m.group(0) for m in re.finditer(r'<div class="notice">.*?</div>', html, re.S)],
        "relation": [m.group(0) for m in re.finditer(r'<td data-label="Relation".*?</td>', html, re.S)],
    }
    return out


def main() -> None:
    for name in PAGES:
        b_path = ROOT / ".tmp/t16-before/name" / f"{name}.html"
        a_path = ROOT / ".tmp/t16-after/name" / f"{name}.html"
        b = io.open(b_path, encoding="utf-8").read()
        a = io.open(a_path, encoding="utf-8").read()
        print(f"\n{'=' * 70}\n{name}: before {len(b):,} B → after {len(a):,} B "
              f"({len(a) - len(b):+,} B)")
        bf, af = fragments(b), fragments(a)
        for kind in ("notice", "relation"):
            for i in range(max(len(bf[kind]), len(af[kind]))):
                bv = bf[kind][i] if i < len(bf[kind]) else "(none)"
                av = af[kind][i] if i < len(af[kind]) else "(none)"
                if bv == av:
                    continue
                print(f"  [{kind} #{i + 1}]")
                print(f"    before: {bv}")
                print(f"    after : {av}")
        # 其它差异（应当只有 CSS/无）：整页行级 diff 前 6 条
        diff = list(difflib.unified_diff(b.splitlines(), a.splitlines(), lineterm="", n=0))
        changed = [d for d in diff if d.startswith(("+", "-")) and not d.startswith(("+++", "---"))]
        print(f"  整页 diff 行数: {len(changed)}（{len(changed)} 行变化）")


if __name__ == "__main__":
    main()
