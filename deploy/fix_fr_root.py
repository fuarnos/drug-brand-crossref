#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把语言落地页 `site/dist/<lang>/index.html` 的内容写成 R2 对象键 `<lang>/`（末尾带斜杠）。

为什么需要它（临时兜底，最终应在 Cloudflare 为每种语言加 Transform Rule）
--------------------------------------------------------------------
Cloudflare 的 Transform Rules 目前只覆盖 4 条语言根：`/`、`/zh/`、`/es/`、`/zh-hant/`
各自映射到 `<lang>/index.html`，**没有 `/fr/`，也没有 v0.13.8 的 `/ko/`** →
落地页 `https://drugcrossref.com/fr/`、`/ko/` 返回 404（而 `/fr/index.html`、
`/ko/index.html` 是 200）。

在规则补齐之前，用「对象键 `fr/` / `ko/`」直接绕过：R2 会把这个键当作
`/fr/`、`/ko/` 的实体响应。
注意 `rclone copyto` 做不到——它把结尾斜杠当目录（`CRITICAL: ... is a directory`，不发请求），
所以这里用 S3 SigV4 直接 PUT。

重要
----
* 这些对象**不在 `site/dist` 里**，下一次 `sync_r2.ps1` 会把它当多余对象删掉 →
  `deploy/sync_r2.ps1` 在同步成功后自动调用本脚本按语言列表重放（失败只警告，不影响上传结果）。
* 默认语言列表 = `fr,ko`（`LANG_ROOTS`）；新增 UI 语言时**同时**改这里、
  `deploy/verify_live.py` 的 `LANG_ROOTS` 与 `data/languages.json`。
  `/`、`/zh/`、`/es/`、`/zh-hant/` 已有 Transform Rule，不需要这种兜底。
* 只读 `site/dist/<lang>/index.html` 与仓库根的 `.env`，不写库、不改 dist。

用法
----
    python deploy/fix_fr_root.py --dist site/dist                  # 写 fr/ + ko/
    python deploy/fix_fr_root.py --dist site/dist --langs fr,ko    # 显式语言列表
    python deploy/fix_fr_root.py --dist site/dist --dry-run        # 只检查，不发请求

退出码：0 全部成功 / 1 至少一个 PUT 失败 / 2 配置或依赖缺失（缺 .env、缺 botocore、
       没有可写的源文件）。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 需要「对象键兜底」的语言根（按 Cloudflare Transform Rules 的缺口维护）。
# 新增 UI 语言时同步 deploy/verify_live.py 的 LANG_ROOTS 与 data/languages.json。
LANG_ROOTS: tuple[str, ...] = ("fr", "ko")
CONTENT_TYPE = "text/html; charset=utf-8"
LANG_RE = re.compile(r"^[a-z]{2}(?:-[a-z]+)?$")


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if t and not t.startswith("#") and "=" in t:
            k, _, v = t.partition("=")
            env[k.strip()] = v.strip().strip('"')
    return env


def parse_langs(raw: str) -> list[str]:
    """`fr,ko` → ["fr", "ko"]：去空白、去结尾斜杠、去重、校验语言标签。"""
    out: list[str] = []
    for part in (raw or "").split(","):
        lang = part.strip().strip("/").lower()
        if not lang:
            continue
        if not LANG_RE.match(lang):
            raise ValueError(f"非法语言标签 {part!r}（应形如 fr / ko / zh-hant）")
        if lang not in out:
            out.append(lang)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="把 <lang>/index.html 写成 R2 对象键 <lang>/（临时兜底）")
    ap.add_argument("--dist", type=Path, default=ROOT / "site" / "dist")
    ap.add_argument("--env", type=Path, default=ROOT / ".env")
    ap.add_argument("--langs", default=",".join(LANG_ROOTS),
                    help="逗号分隔的语言根列表（默认 %(default)s；新增 UI 语言时同步维护）")
    ap.add_argument("--dry-run", action="store_true", help="只检查，不发 PUT")
    args = ap.parse_args()

    try:
        langs = parse_langs(args.langs)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    if not langs:
        print("ERROR: --langs 为空，没有可写的语言根")
        return 2

    # 逐语言收集源文件；缺失只警告，不阻断其它语言（例如新语言刚上线、dist 还没重建）。
    plan: list[tuple[str, Path, bytes]] = []
    for lang in langs:
        src = args.dist / lang / "index.html"
        if not src.exists():
            print(f"WARN: 源文件不存在 {src}（跳过 /{lang}/ 兜底）")
            continue
        plan.append((lang, src, src.read_bytes()))
    if not plan:
        print(f"WARN: {args.dist} 下没有任何语言落地页（检查语言列表 {langs} 或 dist 路径）")
        return 2

    env = read_env(args.env)
    need = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    missing = [k for k in need if not env.get(k)]
    if missing:
        print(f"WARN: .env 缺 {', '.join(missing)}（跳过语言根兜底）")
        return 2

    if args.dry_run:
        for lang, src, body in plan:
            print(f"[dry-run] 将 PUT r2:{env['R2_BUCKET']}/{lang}/ ← {src}（{len(body):,} B）")
        return 0

    try:
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import Credentials
    except ImportError:
        print("WARN: 缺 botocore，无法签名（跳过语言根兜底）")
        return 2

    host = f"{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
    credentials = Credentials(env["R2_ACCESS_KEY_ID"], env["R2_SECRET_ACCESS_KEY"])
    failed = 0
    for lang, src, body in plan:
        key = f"{lang}/"
        url = f"https://{host}/{env['R2_BUCKET']}/{key}"
        now = datetime.now(timezone.utc)
        req = AWSRequest(method="PUT", url=url, data=body, headers={
            "Host": host,
            "Content-Type": CONTENT_TYPE,
            "Content-Length": str(len(body)),
            "x-amz-content-sha256": hashlib.sha256(body).hexdigest(),
            "x-amz-date": now.strftime("%Y%m%dT%H%M%SZ"),
        })
        SigV4Auth(credentials, "s3", "auto").add_auth(req)
        prepared = req.prepare()
        request = urllib.request.Request(prepared.url, data=body, method="PUT",
                                         headers=dict(prepared.headers))
        try:
            with urllib.request.urlopen(request, timeout=60) as resp:
                print(f"{key} -> PUT {resp.status}（{len(body):,} B, {CONTENT_TYPE}）"
                      f"  # 临时兜底：Cloudflare 为该语言加 Transform Rule 后可删")
        except urllib.error.HTTPError as exc:
            detail = (exc.read() or b"")[:400].decode("utf-8", "replace")
            print(f"WARN: PUT {key} 失败 HTTP {exc.code}：{detail}")
            failed += 1
        except Exception as exc:  # 网络错误等
            print(f"WARN: PUT {key} 失败：{exc!r}")
            failed += 1
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
