"""静态产物托管迁移评估（只读，不上传）。

用途：在把 site/dist 迁到对象存储（Cloudflare R2 / S3）前，算出真实规模与费用，
并打印可直接执行的同步命令模板。

设计约束：
- **默认 dry-run**：只统计、只打印，不发起任何网络请求；加 --write-commands 才写出命令文件。
- 不改 site/dist、不改 data/drugs.db；发布入口仍是 deploy/publish.ps1（迁移完成后由它调用本脚本的同步步骤）。
- 费用按 Cloudflare R2 公开价：存储 $0.015/GB-月、Class A $4.50/百万、Class B $0.36/百万；
  免费额度：10 GB 存储 / 100 万 Class A / 1000 万 Class B 每月。

用法：
    & $py deploy/sync_static.py                 # 统计 + 费用 + 命令模板
    & $py deploy/sync_static.py --changed-since 2026-10-30T00:00:00   # 估增量发布
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "site" / "dist"

# Cloudflare R2 公开价（2026-10 口径，仅用于估算）
PRICE_STORAGE_PER_GB_MONTH = 0.015
PRICE_CLASS_A_PER_MILLION = 4.50
PRICE_CLASS_B_PER_MILLION = 0.36
FREE_STORAGE_GB = 10.0
FREE_CLASS_A = 1_000_000
FREE_CLASS_B = 10_000_000


def scan(changed_since: datetime | None) -> dict[str, object]:
    """扫描 dist，返回文件数 / 字节数 / 扩展名分布 / 增量文件数。"""
    files = 0
    total = 0
    changed = 0
    zero = 0
    by_ext: Counter[str] = Counter()
    by_ext_bytes: Counter[int] = Counter()
    largest: list[tuple[int, str]] = []

    for path in DIST.rglob("*"):
        if not path.is_file():
            continue
        st = path.stat()
        files += 1
        total += st.st_size
        ext = path.suffix.lower() or "(none)"
        by_ext[ext] += 1
        by_ext_bytes[ext] += st.st_size
        if st.st_size == 0:
            zero += 1
        if changed_since is not None and datetime.fromtimestamp(st.st_mtime) >= changed_since:
            changed += 1
        largest.append((st.st_size, path.relative_to(DIST).as_posix()))

    largest.sort(reverse=True)
    return {
        "files": files,
        "bytes": total,
        "zero_byte": zero,
        "changed": changed,
        "by_ext": [(ext, by_ext[ext], by_ext_bytes[ext]) for ext in sorted(by_ext, key=by_ext_bytes.get, reverse=True)],
        "largest": largest[:5],
    }


def money(usd: float) -> str:
    return f"${usd:,.4f}（约 {usd * 7.2:,.2f} 元）"


def main() -> int:
    ap = argparse.ArgumentParser(description="静态产物托管迁移评估（dry-run）")
    ap.add_argument("--dist", default=str(DIST), help="静态产物目录（默认 site/dist）")
    ap.add_argument("--changed-since", default="", help="ISO 时间；估算该时间之后变动的文件（增量发布）")
    ap.add_argument("--bucket", default="drug-brand-crossref", help="目标 bucket 名（仅用于命令模板）")
    ap.add_argument("--write-commands", default="", help="把同步命令写到该文件（默认不写）")
    ap.add_argument("--json-out", default="", help="把统计结果写到该 JSON 文件")
    args = ap.parse_args()

    dist = Path(args.dist)
    if not dist.is_dir():
        print(f"[FAIL] 找不到静态产物目录：{dist}")
        return 1

    since = datetime.fromisoformat(args.changed_since) if args.changed_since else None
    info = scan(since)
    files = int(info["files"])
    total = int(info["bytes"])
    gb = total / 1024**3

    print("== 静态产物规模 ==")
    print(f"文件数      : {files:,}")
    print(f"总字节      : {total:,} B（{total / 1024**2:,.2f} MiB / {gb:.3f} GiB）")
    print(f"0 字节文件  : {info['zero_byte']}")
    if since is not None:
        print(f"增量（自 {args.changed_since}）: {info['changed']:,} 文件")

    print("\n== 扩展名分布（Top 6，按字节） ==")
    for ext, n, b in info["by_ext"][:6]:  # type: ignore[index]
        print(f"{ext:<8} {n:>8,} 个 {b / 1024**2:>9,.2f} MiB")

    print("\n== 最大文件 Top 5 ==")
    for size, rel in info["largest"]:  # type: ignore[index]
        print(f"{size / 1024**2:>8,.2f} MiB  {rel}")

    # ── 费用估算 ─────────────────────────────────────────────────────────
    writes = int(info["changed"]) if since is not None else files
    storage_cost = max(0.0, gb - FREE_STORAGE_GB) * PRICE_STORAGE_PER_GB_MONTH
    write_cost = max(0, writes - FREE_CLASS_A) / 1_000_000 * PRICE_CLASS_A_PER_MILLION
    print("\n== Cloudflare R2 估算（免费额度：10 GB / 100 万写 / 1000 万读） ==")
    print(f"存储        : {gb:.3f} GiB → 超出额度 {max(0.0, gb - FREE_STORAGE_GB):.3f} GiB → {money(storage_cost)}/月")
    print(f"本次写入    : {writes:,} 次 Class A → 超出额度 {max(0, writes - FREE_CLASS_A):,} → {money(write_cost)}")
    if storage_cost == 0 and write_cost == 0:
        print("结论        : **在免费额度内（$0/月）**；只有域名年费（约 70 元/年）是硬成本。")

    # ── 命令模板 ─────────────────────────────────────────────────────────
    remote = f"r2:{args.bucket}"
    sync_cmd = (
        f'rclone sync "{dist}" {remote} --checksum --fast-list --transfers 32 --checkers 32 '
        '--header-upload "Cache-Control: public, max-age=3600"'
    )
    print("\n== 同步命令模板（需先装 rclone 并配置 r2 remote） ==")
    print(sync_cmd)
    print("说明：HTML 的缓存策略建议在 Cloudflare Cache Rules 里按路径覆盖，不要只靠 header。")

    if args.write_commands:
        out = Path(args.write_commands)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(sync_cmd + "\n", encoding="utf-8")
        print(f"\n已写出命令文件：{out}")

    if args.json_out:
        payload = {"files": files, "bytes": total, "gb": round(gb, 4), "writes": writes}
        Path(args.json_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写出统计：{args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
