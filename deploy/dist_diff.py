#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""`site/dist` 两版差分（T18）：路径 + 大小 + **内容哈希**，四类分类 + §6 三条判定提示。

为什么需要它
------------
v1.2.5 发布时 A/B 只按「路径 + 大小」差分，对**同长度内容替换**有盲区：本版 **78 个文件**
内容变了但字节数没变（`v1.2.4 → v1.2.5`、`2026-11-25 → 2026-11-26`、hashed 资源名都是等长替换），
清单差分看不见，只能靠 `sync_r2.ps1 -DryRun`（rclone `--checksum`，按内容哈希）交叉核平
（见 `reports/2026-11-26-v125-release.md` §4 末）。本脚本把这套交叉核对固化成可复用工具：
清单带 SHA-256，四类分开数，`changed(content-only)` 就是那条盲区的直接证据。

四类
----
| 类别 | 含义 |
|---|---|
| `added` | 只在新版出现（新增页面 / 新增资源） |
| `removed` | 只在旧版出现（被删页面 / 旧 hashed 资源） |
| `changed(size)` | 两版都有、**大小变了** |
| `changed(content-only)` | 两版都有、**大小相同但内容哈希不同**（旧口径的盲区） |

清单格式（UTF-8 **无 BOM**，T16 口径）：每行 `相对路径<TAB>字节数<TAB>sha256`；
兼容只有前两列的旧清单（此时 `changed(content-only)` 不可见，会明确 WARN，不静默）。

三条判定（`AGENTS.md` §6「内容扩容例外」）
------------------------------------------
① `added` 是否全在 `product/`（+ `assets/` 少量 + `sitemap-<n>.xml` 分片）；
② **页面** `removed` 是否为 0（`assets/` 之外；保活清单里的旧哈希不算页面）；
③ 长尾六类（`name` / `drug` / `combo` / `maker` / `atc` / `cat`）的变化是否只由
   「新增静态页链接」引起：两边都是目录时，把两种产品链接**都归一成 `href="P:<pid>"`**
   再逐字比较，`links-only` = 除链接目标外无差异，`non-link` = 还有别的内容变化（要人工看）。

用法
----
    # 1) 目录 → 清单（含哈希；之后可离线比较、可进报告）
    python deploy/dist_diff.py --write-manifest .tmp/a.tsv --root .tmp/a
    # 2) 两份清单比较
    python deploy/dist_diff.py --before .tmp/a.tsv --after .tmp/b.tsv
    # 3) 直接比两棵目录（就地算哈希，不落清单；长尾链接自动核实）
    python deploy/dist_diff.py --before .tmp/a --after .tmp/b
    # 4) 真实 dist 自检（同目录 vs 同目录，应 0 差异）
    python deploy/dist_diff.py --before site/dist --after site/dist --expect-identical
    # 5) 机器可读
    python deploy/dist_diff.py --before A --after B --json .tmp/diff.json

退出码：0 分析完成（默认）／1 用了 `--expect-identical` 而确实有差异 ／
        2 参数或输入错误（路径不存在、清单格式坏）。

只读：不写 dist、不碰 R2、不碰库。清单输出用 `--write-manifest` 显式指定时才会写文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LONGTAIL = ("name", "drug", "combo", "maker", "atc", "cat")
SHARD_RE = re.compile(r"sitemap-\d+\.xml")
# 两种产品链接形态：`../product/<pid>.html`（静态页）与 `../product.html?pid=<pid>`（长尾）。
# 归一化只替换 href 里的目标，不碰别的字符 —— 这样才能证明「同位置仅链接目标变化」。
STATIC_RE = re.compile(r'href="(?:\.\./)?product/(?P<pid>[^"/]+)\.html"')
LONG_RE = re.compile(r'href="(?:\.\./)?product\.html\?pid=(?P<pid>[^"]+)"')
SAMPLE_DEFAULT = 5


@dataclass
class Entry:
    """一个文件的元信息：大小必有，哈希可能缺（旧两列清单）。"""

    size: int
    sha: str | None = None


@dataclass
class Manifest:
    """一份清单：路径 → Entry，外加上下文（来源、编码、非 ASCII 行数）。"""

    entries: dict[str, Entry] = field(default_factory=dict)
    source: str = ""
    encoding: str = "utf-8"
    non_ascii: int = 0
    paths: set[str] = field(default_factory=set)


# ── 读取 / 生成清单 ───────────────────────────────────────────────────────────
def read_manifest(path: Path) -> Manifest:
    """读清单（UTF-8 无 BOM；兼容 2 列 / 3 列）。坏行直接报错，不静默跳过。"""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        print(f"WARN: {path} 带 UTF-8 BOM（T16 口径应为无 BOM），已按 utf-8-sig 读", file=sys.stderr)
        text = raw.decode("utf-8-sig")
    else:
        text = raw.decode("utf-8")
    man = Manifest(source=str(path))
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = line.rsplit("\t", 2)
        if len(parts) == 2:
            rel, size_s = parts
            sha = None
        elif len(parts) == 3:
            rel, size_s, sha = parts
            sha = sha.strip() or None
        else:
            raise SystemExit(f"ERROR: {path} 第 {lineno} 行不是 2/3 列：{line[:120]!r}")
        try:
            size = int(size_s)
        except ValueError:
            raise SystemExit(f"ERROR: {path} 第 {lineno} 行大小不是整数：{line[:120]!r}") from None
        man.entries[rel] = Entry(size, sha)
        if not rel.isascii():
            man.non_ascii += 1
    return man


def _hash_one(root: Path, rel: str, algo: str) -> tuple[str, int, str]:
    full = root / rel.replace("/", os.sep)
    h = hashlib.new(algo)
    size = 0
    with open(full, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            h.update(chunk)
    return rel, size, h.hexdigest()


def scan_dir(root: Path, algo: str = "sha256", jobs: int = 8) -> Manifest:
    """把目录扫成清单（含内容哈希）。哈希在 I/O 线程池里算，362k 文件约 30–60 s。"""
    man = Manifest(source=str(root))
    rels: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        for name in filenames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            rels.append(rel)
    rels.sort()
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for rel, size, digest in pool.map(lambda r: _hash_one(root, r, algo), rels):
            man.entries[rel] = Entry(size, digest)
            if not rel.isascii():
                man.non_ascii += 1
    return man


def write_manifest(man: Manifest, out: Path, algo: str) -> None:
    """写清单：UTF-8 无 BOM、`\\n` 换行、按路径排序（可 diff、可进 git）。"""
    lines = [f"{rel}\t{e.size}\t{e.sha}" for rel, e in sorted(man.entries.items())]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out} rows={len(lines)} bytes={out.stat().st_size} "
          f"encoding=utf-8-algo={algo} bom={out.read_bytes()[:3] == b'\xef\xbb\xbf'} "
          f"non-ascii-rows={man.non_ascii}")


# ── 差分 ─────────────────────────────────────────────────────────────────────
def top(path: str) -> str:
    return path.split("/", 1)[0] if "/" in path else "(root)"


def classify(before: Manifest, after: Manifest) -> dict[str, list[str]]:
    b, a = before.entries, after.entries
    added = sorted(set(a) - set(b))
    removed = sorted(set(b) - set(a))
    both = sorted(set(a) & set(b))
    changed_size = [p for p in both if a[p].size != b[p].size]
    both_hash = [p for p in both if a[p].sha and b[p].sha]
    changed_content = [p for p in both_hash if a[p].size == b[p].size and a[p].sha != b[p].sha]
    return {
        "added": added,
        "removed": removed,
        "changed(size)": changed_size,
        "changed(content-only)": changed_content,
        "both": both,
        "both_hash": both_hash,
    }


def normalize_links(text: str) -> str:
    """把两种产品链接都归一成 `href="P:<pid>"`（其余字符原样保留）。"""
    out = STATIC_RE.sub(lambda m: f'href="P:{m.group("pid")}"', text)
    return LONG_RE.sub(lambda m: f'href="P:{m.group("pid")}"', out)


def check_longtail_links(before_dir: Path, after_dir: Path,
                         changed: list[str], limit: int) -> dict[str, object]:
    """③ 精验：长尾页的变化是否只由产品链接目标变化引起（需两边都是目录）。"""
    longtail_changed = [p for p in changed if top(p) in LONGTAIL]
    picked = longtail_changed[:limit]
    links_only: list[str] = []
    non_link: list[str] = []
    for rel in picked:
        b_file = before_dir / rel.replace("/", os.sep)
        a_file = after_dir / rel.replace("/", os.sep)
        if not (b_file.is_file() and a_file.is_file()):     # 只比两侧都在的页（新增/删除另归类）
            continue
        b = b_file.read_bytes().decode("utf-8", "replace")
        a = a_file.read_bytes().decode("utf-8", "replace")
        if normalize_links(b) == normalize_links(a):
            links_only.append(rel)
        else:
            non_link.append(rel)
    return {
        "longtail_changed": len(longtail_changed),
        "checked": len(picked),
        "skipped": len(longtail_changed) - len(picked),
        "links_only": links_only,
        "non_link": non_link,
    }


def criteria(before: Manifest, after: Manifest, classes: dict[str, list[str]],
             longtail: dict[str, object] | None) -> dict[str, object]:
    """`AGENTS.md` §6 内容扩容例外三条判定（只给提示，不做放行决定）。"""
    added = classes["added"]
    bad_added = [p for p in added
                 if top(p) not in ("product", "assets") and not SHARD_RE.fullmatch(p)]
    page_removed = [p for p in classes["removed"] if top(p) != "assets"]
    longtail_removed = [p for p in classes["removed"] if top(p) in LONGTAIL]
    longtail_changed = [p for p in (classes["changed(size)"] + classes["changed(content-only)"])
                        if top(p) in LONGTAIL]
    out: dict[str, object] = {
        "① added 是否全在 product//assets//sitemap-N.xml": {
            "ok": not bad_added, "violations": len(bad_added), "samples": bad_added[:5],
            "by_dir": dict(Counter(top(p) for p in added).most_common()),
        },
        "② 页面 removed（assets/ 之外）是否为 0": {
            "ok": not page_removed, "count": len(page_removed), "samples": page_removed[:5],
            "assets_removed": [p for p in classes["removed"] if top(p) == "assets"],
        },
        "③ 长尾页变化是否只由新增静态页链接引起": {
            "longtail_changed": len(longtail_changed),
            "longtail_removed": len(longtail_removed),
            "longtail_removed_ok": not longtail_removed,
        },
    }
    if longtail is None:
        nothing_changed = not (classes["changed(size)"] or classes["changed(content-only)"])
        out["③ 长尾页变化是否只由新增静态页链接引起"].update({  # type: ignore[union-attr]
            "ok": True if nothing_changed else None,
            "note": "两版没有任何共有文件变化（自检场景）" if nothing_changed
                    else "输入是清单，未做逐字节核实；两边都给目录才会自动验 link-only"})
    else:
        non_link = longtail["non_link"]
        out["③ 长尾页变化是否只由新增静态页链接引起"].update({  # type: ignore[union-attr]
            "checked": longtail["checked"],
            "skipped": longtail["skipped"],
            "links_only": len(longtail["links_only"]),
            "non_link": len(non_link),  # type: ignore[arg-type]
            "non_link_samples": list(non_link)[:5],  # type: ignore[call-overload]
            "ok": not non_link,  # type: ignore[arg-type]
        })
    return out


# ── 输出 ─────────────────────────────────────────────────────────────────────
def print_report(before: Manifest, after: Manifest, classes: dict[str, list[str]],
                 crit: dict[str, object], samples: int, algo: str) -> None:
    print(f"before: {before.source}  files={len(before.entries):,}  编码={before.encoding}（无 BOM）"
          f"  非 ASCII 路径={before.non_ascii:,}")
    print(f"after : {after.source}  files={len(after.entries):,}  编码={after.encoding}（无 BOM）"
          f"  非 ASCII 路径={after.non_ascii:,}")
    if not classes["both_hash"] and classes["both"]:
        print("WARN: 至少一份清单没有哈希（旧 2 列清单）→ changed(content-only) 不可见，"
              "请用 --write-manifest 或直接给目录重算", file=sys.stderr)
    print()
    print(f"四类（algo={algo}）：")
    for key in ("added", "removed", "changed(size)", "changed(content-only)"):
        items = classes[key]
        dist = dict(Counter(top(p) for p in items).most_common())
        print(f"  {key:<22} {len(items):>9,}  {dist if dist else ''}")
    for key in ("added", "removed", "changed(size)", "changed(content-only)"):
        items = classes[key]
        if items and samples:
            print(f"  {key} 样例（前 {min(samples, len(items))} 条）：")
            for p in items[:samples]:
                b = before.entries.get(p)
                a = after.entries.get(p)
                bs = f"{b.size:,}B" if b else "-"
                as_ = f"{a.size:,}B" if a else "-"
                print(f"    {p}  [{bs} -> {as_}]")
    print()
    print("三条判定（AGENTS.md §6 内容扩容例外，仅提示）：")
    for name, info in crit.items():  # type: ignore[union-attr]
        detail = {k: v for k, v in info.items() if k != "ok"}  # type: ignore[union-attr]
        ok = info.get("ok")  # type: ignore[union-attr]
        flag = "成立" if ok is True else ("未核实（清单模式）" if ok is None else "需人工看")
        print(f"  {name}: {flag}  {json.dumps(detail, ensure_ascii=False)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="site/dist 两版差分：路径 + 大小 + 内容哈希（四类）+ §6 三条判定提示")
    ap.add_argument("--before", help="旧版：目录或清单文件（.tsv/.txt）")
    ap.add_argument("--after", help="新版：目录或清单文件（.tsv/.txt）")
    ap.add_argument("--write-manifest", metavar="OUT",
                    help="把 --root 扫成清单写到 OUT（UTF-8 无 BOM），不比较")
    ap.add_argument("--root", help="配合 --write-manifest：要扫的目录（默认 site/dist）")
    ap.add_argument("--algo", default="sha256", choices=("sha256", "md5"),
                    help="内容哈希算法（默认 %(default)s）")
    ap.add_argument("--jobs", type=int, default=8, help="算哈希的线程数（默认 %(default)s）")
    ap.add_argument("--samples", type=int, default=SAMPLE_DEFAULT, help="每类打印的样例条数")
    ap.add_argument("--json", metavar="OUT", nargs="?", const="-", default=None,
                    help="输出 JSON（省略路径 = 打到 stdout；给了路径 = 写文件，UTF-8 无 BOM）")
    ap.add_argument("--check-links", action="store_true",
                    help="强制做 ③ 的逐字节核实（两边都是目录时默认就会做）")
    ap.add_argument("--check-links-max", type=int, default=200,
                    help="③ 最多逐字节核实多少个长尾页（默认 %(default)s）")
    ap.add_argument("--expect-identical", action="store_true",
                    help="要求四类全为 0（不同则 exit 1）；自检/CI 用")
    args = ap.parse_args(argv)

    if args.write_manifest:
        root = Path(args.root or (ROOT / "site" / "dist"))
        if not root.is_dir():
            print(f"ERROR: 目录不存在：{root}", file=sys.stderr)
            return 2
        write_manifest(scan_dir(root, args.algo, args.jobs), Path(args.write_manifest), args.algo)
        return 0

    if not args.before or not args.after:
        ap.error("需要 --before 与 --after（或 --write-manifest + --root）")
    b_path, a_path = Path(args.before), Path(args.after)
    for p in (b_path, a_path):
        if not p.exists():
            print(f"ERROR: 输入不存在：{p}", file=sys.stderr)
            return 2

    before = scan_dir(b_path, args.algo, args.jobs) if b_path.is_dir() else read_manifest(b_path)
    after = scan_dir(a_path, args.algo, args.jobs) if a_path.is_dir() else read_manifest(a_path)
    before.encoding = after.encoding = "utf-8"

    classes = classify(before, after)
    changes = (classes["added"] + classes["removed"]
               + classes["changed(size)"] + classes["changed(content-only)"])
    # ③ 只比「两版都有、内容变了」的页（added / removed 分别由 ① / ② 判定）
    changed_both = sorted(set(classes["changed(size)"]) | set(classes["changed(content-only)"]))
    do_links = (args.check_links or (b_path.is_dir() and a_path.is_dir())) and bool(changed_both)
    longtail = (check_longtail_links(b_path, a_path, changed_both, args.check_links_max)
                if do_links else None)
    crit = criteria(before, after, classes, longtail)

    print_report(before, after, classes, crit, args.samples, args.algo)
    if longtail is not None:
        print(f"\n③ 逐字节核实：长尾变化 {longtail['longtail_changed']} 页，"
              f"核实 {longtail['checked']} 页（跳过 {longtail['skipped']}），"
              f"links-only {len(longtail['links_only'])} / non-link {len(longtail['non_link'])}")
        for p in list(longtail["non_link"])[:5]:
            print(f"    non-link: {p}")
    total = len(changes)
    print(f"\n合计差异 {total:,} 文件（added {len(classes['added']):,} / removed {len(classes['removed']):,} / "
          f"changed(size) {len(classes['changed(size)']):,} / changed(content-only) "
          f"{len(classes['changed(content-only)']):,}）")

    if args.json is not None:
        payload = {
            "before": {"source": before.source, "files": len(before.entries)},
            "after": {"source": after.source, "files": len(after.entries)},
            "algo": args.algo,
            "counts": {k: len(classes[k]) for k in
                       ("added", "removed", "changed(size)", "changed(content-only)")},
            "samples": {k: classes[k][:args.samples] for k in
                        ("added", "removed", "changed(size)", "changed(content-only)")},
            "criteria": crit,
            "longtail_link_check": longtail,
            "total_differences": total,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.json == "-":
            print(text)
        else:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n", encoding="utf-8", newline="\n")
            print(f"wrote {out}")

    if args.expect_identical and total:
        print(f"ERROR: --expect-identical 但存在 {total:,} 处差异", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
