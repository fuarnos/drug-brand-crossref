#!/usr/bin/env python
"""R2 凭证形状预检：只看长度与字符形状，**不打印任何密钥内容**。

背景：2026-11-11 v0.11.0 发布后首次同步 R2 时，`.env` 里
`R2_SECRET_ACCESS_KEY` 只有 62 位十六进制（R2 应为 64 位），
rclone 报 `403 SignatureDoesNotMatch`，白等一轮同步。

本脚本在同步前跑一遍：形状不对就 exit 2，避免拿错密钥去撞 API。
输出只含「长度 / 是否全十六进制 / 首尾是否有空白或引号」，
密钥值本身不会出现在 stdout / 日志里。

用法：
    python deploy/check_r2_env.py            # 读仓库根 .env
    python deploy/check_r2_env.py --env .env # 指定文件

退出码：0 = 形状正常；2 = 缺键或形状不对。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# R2（S3 兼容）密钥形状：account id / access key id 32 位 hex，secret 64 位 hex。
EXPECTED = {
    "R2_ACCOUNT_ID": (32, True),
    "R2_ACCESS_KEY_ID": (32, True),
    "R2_SECRET_ACCESS_KEY": (64, True),
    "R2_BUCKET": (0, False),  # 只要求非空，不强求 hex
}


def read_env(path: Path) -> dict[str, str]:
    """读 .env（不吃引号外的空白；值原样返回，便于检查首尾异常）。"""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value  # 注意：不 strip，首尾空白/引号要能被看出来
    return out


def describe(value: str) -> str:
    """输出长度与形状，不输出内容。"""
    trimmed = value.strip()
    is_hex = bool(trimmed) and all(c in "0123456789abcdefABCDEF" for c in trimmed)
    flags: list[str] = []
    if value != trimmed:
        flags.append("首尾有空白")
    if trimmed.startswith(("'", '"')) or trimmed.endswith(("'", '"')):
        flags.append("带引号")
    if any(ord(c) < 32 or ord(c) > 126 for c in trimmed):
        flags.append("含非 ASCII/控制字符")
    return f"len={len(trimmed)} hex={is_hex}" + (f" ⚠{'/'.join(flags)}" if flags else "")


def main() -> int:
    ap = argparse.ArgumentParser(description="R2 凭证形状预检（不打印密钥）")
    ap.add_argument("--env", default=str(ROOT / ".env"), help=".env 路径")
    args = ap.parse_args()

    env = read_env(Path(args.env))
    if not env:
        print(f"FAIL: 读不到 {args.env}（或文件为空）")
        return 2

    bad: list[str] = []
    for key, (want_len, want_hex) in EXPECTED.items():
        value = env.get(key, "")
        trimmed = value.strip()
        if not trimmed:
            print(f"FAIL {key}: 缺失或为空")
            bad.append(key)
            continue
        shape = describe(value)
        ok = True
        if want_len and len(trimmed) != want_len:
            ok = False
        if want_hex and not all(c in "0123456789abcdefABCDEF" for c in trimmed):
            ok = False
        if value != trimmed or trimmed.startswith(("'", '"')):
            ok = False
        print(f"{'OK  ' if ok else 'FAIL'} {key}: {shape}" + ("" if want_len == 0 else f"（应为 {want_len} 位 hex）"))
        if not ok:
            bad.append(key)

    if bad:
        print(""
              "\n结论：形状不对，先别同步。R2 Secret Access Key 只能在面板创建 token 时复制一次，"
              "请重新生成并整段粘贴（64 位十六进制，不要引号/空格）。")
        return 2
    print("\n结论：形状正常，可以跑 deploy/sync_r2.ps1 -CheckOnly。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
