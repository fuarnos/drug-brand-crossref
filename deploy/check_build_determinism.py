#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""构建确定性检查：两次 `site/build.py` 的产物是否逐字节一致。

背景（task-14）：v0.9.7 发布时 gh-pages 有 112,692 个文件变化，但实际只改了少量代码。
根因之一是 `?v=<unix 时间戳>` 写进了每一页的 <head>。本脚本用来量化这件事，
并在修完后证明「两次构建逐字节一致」。

用法
----
    # 1) 两个产物目录逐字节对比（按文件 hash；输出按页面族分组）
    python deploy/check_build_determinism.py .tmp/det/a .tmp/det/b

    # 2) 只比某一族（name 页 / drug 页 / data）
    python deploy/check_build_determinism.py .tmp/det/a .tmp/det/b --family name

    # 3) 与线上产物对比「正文是否一致」（忽略 ?v= 版本号差异，顺序变化允许）
    python deploy/check_build_determinism.py .tmp/det/a --against site/dist --sample 200

    # 4) 写/比 hash 清单（CI 用）
    python deploy/check_build_determinism.py .tmp/det/a --write-manifest .tmp/det/a.sha256
    python deploy/check_build_determinism.py .tmp/det/b --check-manifest .tmp/det/a.sha256

退出码：0 = 一致；1 = 有差异（打印计数与样例）。
只读：不改任何产物目录。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 版本号归一：`?v=1699999999` / `?v=a1b2c3d4e5f6` → `?v=VER`；manifest 里的 "v": 数字同样归一。
_VER_QUERY = re.compile(r"\?v=[0-9A-Za-z][0-9A-Za-z.]{0,19}")
_VER_MANIFEST = re.compile(r'"v":\s*[0-9A-Za-z][0-9A-Za-z.]{0,19}')


def norm(text: str) -> str:
    """去掉版本号后再比正文（构建版本号按设计会变，不算内容差异）。"""
    return _VER_MANIFEST.sub('"v":VER', _VER_QUERY.sub("?v=VER", text))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(root: Path) -> dict[str, tuple[int, str]]:
    """相对路径 → (字节数, sha256)。"""
    out: dict[str, tuple[int, str]] = {}
    for p in root.rglob("*"):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = (p.stat().st_size, sha256_of(p))
    return out


def family_of(rel: str) -> str:
    """页面族：name/ drug/ combo/ maker/ atc/ cat/ data/ assets/ 顶层 *.html。"""
    parts = rel.split("/")
    if len(parts) == 1:
        if parts[0].endswith(".html"):
            return "top-html"
        return "top-" + (parts[0].rsplit(".", 1)[-1] if "." in parts[0] else "other")
    if parts[0] == "data" and len(parts) > 2 and parts[1] == "idx":
        return "data/idx"
    return parts[0]


def first_diff_line(a: str, b: str) -> str:
    """给出一页第一处不同的行（截 160 字符），便于定位生成代码。"""
    al, bl = a.splitlines(), b.splitlines()
    for i, (x, y) in enumerate(zip(al, bl)):
        if x != y:
            return f"L{i + 1}: {x.strip()[:160]}  ||  {y.strip()[:160]}"
    if len(al) != len(bl):
        return f"行数不同：{len(al)} vs {len(bl)}"
    return "（仅尾部换行/不可见字符不同）"


def compare_dirs(a: Path, b: Path, family: str | None, show: int,
                 json_out: Path | None = None) -> int:
    sa, sb = scan(a), scan(b)
    only_a = sorted(set(sa) - set(sb))
    only_b = sorted(set(sb) - set(sa))
    common = sorted(set(sa) & set(sb))
    differ = [r for r in common if sa[r] != sb[r]]

    def counted(rel: str) -> bool:
        return family is None or family_of(rel) == family

    bytes_a = sum(sa[r][0] for r in differ if counted(r))
    print(f"A = {a}  files {len(sa):,}  bytes {sum(v[0] for v in sa.values()):,}")
    print(f"B = {b}  files {len(sb):,}  bytes {sum(v[0] for v in sb.values()):,}")
    print(f"只在 A: {len(only_a):,}   只在 B: {len(only_b):,}   共有: {len(common):,}")
    print(f"内容不同: {len(differ):,}（占共有 {100 * len(differ) / max(len(common), 1):.1f}%），"
          f"涉及 A 侧字节 {bytes_a:,}")

    by_fam: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # [共, 不同, 字节]
    for r in common:
        f = family_of(r)
        by_fam[f][0] += 1
        if sa[r] != sb[r]:
            by_fam[f][1] += 1
            by_fam[f][2] += sa[r][0]
    print("\n按页面族（共 / 不同 / A 侧字节）：")
    for f, (n, d, by) in sorted(by_fam.items(), key=lambda kv: -kv[1][1]):
        if d or family is None:
            print(f"  {f:<14}{n:>8,}  {d:>8,}  {by:>14,}")

    if differ and show:
        print(f"\n差异样例（前 {min(show, len(differ))} 个）：")
        for r in differ[:show]:
            print(f"  {r}  {sa[r][0]}B → {sb[r][0]}B")
            if r.endswith((".html", ".json", ".xml", ".txt", ".js", ".css")):
                try:
                    da = (a / r).read_text(encoding="utf-8")
                    db = (b / r).read_text(encoding="utf-8")
                    print(f"    {first_diff_line(da, db)}")
                except UnicodeDecodeError:
                    print("    （二进制文件）")

    if only_a or only_b:
        for label, items in (("只在 A", only_a), ("只在 B", only_b)):
            if items:
                print(f"\n{label}（前 5）：{items[:5]}")
    if json_out:
        stats = {
            "a": str(a),
            "b": str(b),
            "files_a": len(sa),
            "files_b": len(sb),
            "bytes_a": sum(v[0] for v in sa.values()),
            "bytes_b": sum(v[0] for v in sb.values()),
            "only_a": len(only_a),
            "only_b": len(only_b),
            "common": len(common),
            "differ": len(differ),
            "differ_bytes_a": bytes_a,
            "by_family": {f: {"common": n, "differ": d, "bytes_changed": by}
                          for f, (n, d, by) in sorted(by_fam.items())},
            "differ_samples": differ[:50],
        }
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n统计已写入 {json_out}")
    ok = not differ and not only_a and not only_b
    print("\n== " + ("一致：两次构建逐字节相同 ==" if ok else "不一致：见上表 =="))
    return 0 if ok else 1


def sample_paths(root: Path, sample: int) -> list[str]:
    """确定性抽样：所有 HTML 按路径排序后等距取 sample 个（跨页面族均衡）。"""
    html = sorted(p.relative_to(root).as_posix()
                  for p in root.rglob("*.html") if p.is_file())
    if sample >= len(html):
        return html
    step = len(html) / sample
    return [html[min(int(i * step), len(html) - 1)] for i in range(sample)]


def compare_against(build: Path, dist: Path, sample: int) -> int:
    """与线上产物比「正文」：忽略 ?v= 版本号，差集必须为空。"""
    picks = sample_paths(build, sample)
    differ: list[tuple[str, str]] = []
    identical = 0
    for rel in picks:
        pa, pb = build / rel, dist / rel
        if not pb.exists():
            differ.append((rel, "线上没有这个文件"))
            continue
        ta, tb = pa.read_text(encoding="utf-8"), pb.read_text(encoding="utf-8")
        if norm(ta) == norm(tb):
            identical += 1
        else:
            differ.append((rel, first_diff_line(norm(ta), norm(tb))))
    print(f"抽样 {len(picks)} 页（全站 {sum(1 for _ in build.rglob('*.html')):,} 个 html，"
          f"等距抽取），对照 {dist}")
    print(f"  正文一致：{identical}   有差异：{len(differ)}")
    for rel, why in differ[:20]:
        print(f"  ! {rel}\n    {why}")
    ok = not differ
    print("\n== " + ("正文差集为空 ==" if ok else "正文有差异，见上 =="))
    return 0 if ok else 1


def write_manifest(root: Path, out: Path) -> int:
    sm = scan(root)
    lines = [f"{h}  {rel}" for rel, (_n, h) in sorted(sm.items())]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"写出 {out}（{len(lines):,} 个文件）")
    return 0


def check_manifest(root: Path, ref: Path) -> int:
    want = {}
    for line in ref.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        h, rel = line.split("  ", 1)
        want[rel] = h
    sm = scan(root)
    missing = sorted(set(want) - set(sm))
    extra = sorted(set(sm) - set(want))
    differ = [r for r in sorted(set(sm) & set(want)) if sm[r][1] != want[r]]
    print(f"对照 {ref}：清单 {len(want):,} 个文件；当前 {len(sm):,}")
    print(f"  缺: {len(missing)}  多: {len(extra)}  内容不同: {len(differ)}")
    for r in (missing + extra + differ)[:10]:
        print(f"  ! {r}")
    ok = not (missing or extra or differ)
    print("\n== " + ("与清单一致 ==" if ok else "与清单不一致 =="))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="两次构建产物确定性检查（只读）")
    ap.add_argument("a", type=Path, help="构建产物目录（A）")
    ap.add_argument("b", type=Path, nargs="?", help="构建产物目录（B）；省略时用 --against")
    ap.add_argument("--against", type=Path, help="与另一个产物比正文（忽略 ?v=）：如 site/dist")
    ap.add_argument("--sample", type=int, default=200, help="--against 抽样页数（默认 200）")
    ap.add_argument("--family", help="只统计某个页面族：name/drug/data/assets/top-html…")
    ap.add_argument("--show", type=int, default=8, help="打印几个差异样例（默认 8）")
    ap.add_argument("--write-manifest", type=Path, help="把 A 的 hash 清单写到该文件")
    ap.add_argument("--check-manifest", type=Path, help="用该清单校验 A")
    ap.add_argument("--json", type=Path, help="把统计写成 JSON（报告用）")
    args = ap.parse_args()

    if not args.a.exists():
        raise SystemExit(f"目录不存在：{args.a}")
    if args.write_manifest:
        return write_manifest(args.a, args.write_manifest)
    if args.check_manifest:
        return check_manifest(args.a, args.check_manifest)
    if args.against:
        return compare_against(args.a, args.against, args.sample)
    if not args.b:
        raise SystemExit("要么给第二个目录，要么用 --against / --write-manifest / --check-manifest")
    return compare_dirs(args.a, args.b, args.family, args.show, args.json)


if __name__ == "__main__":
    sys.exit(main())
