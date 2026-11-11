#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 `site/dist/fr/index.html` 的内容写成 R2 对象键 `fr/`（末尾带斜杠）。

为什么需要它（临时兜底，最终应在 Cloudflare 加第 5 条 Transform Rule）
---------------------------------------------------------------------
Cloudflare 的 Transform Rules 目前只有 4 条：`/`、`/zh/`、`/es/`、`/zh-hant/`
各自映射到 `<lang>/index.html`，**没有 `/fr/`** → 法语落地页 `https://drugcrossref.com/fr/`
返回 404（而 `/fr/index.html` 是 200）。

在规则补齐之前，用「对象键 `fr/`」直接绕过：R2 会把这个键当作 `/fr/` 的实体响应。
注意 `rclone copyto` 做不到——它把结尾斜杠当目录（`CRITICAL: ... is a directory`，不发请求），
所以这里用 S3 SigV4 直接 PUT。

重要
----
* 该对象**不在 `site/dist` 里**，下一次 `sync_r2.ps1` 会把它当多余对象删掉 →
  `deploy/sync_r2.ps1` 在同步成功后自动调用本脚本重放（失败只警告，不影响上传结果）。
* 只处理 `fr/`；其它语言已有 Transform Rule，不需要这种兜底。
* 只读 `site/dist/fr/index.html` 与仓库根的 `.env`，不写库、不改 dist。

用法
----
    python deploy/fix_fr_root.py --dist site/dist          # 写 fr/ 对象
    python deploy/fix_fr_root.py --dist site/dist --dry-run # 只检查，不发请求

退出码：0 成功 / 1 HTTP 失败 / 2 配置或依赖缺失（缺 .env、缺 botocore、缺源文件）。
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = "fr/"                                   # 只做这一个键
CONTENT_TYPE = "text/html; charset=utf-8"


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


def main() -> int:
    ap = argparse.ArgumentParser(description="把 fr/index.html 写成 R2 对象键 fr/（临时兜底）")
    ap.add_argument("--dist", type=Path, default=ROOT / "site" / "dist")
    ap.add_argument("--env", type=Path, default=ROOT / ".env")
    ap.add_argument("--dry-run", action="store_true", help="只检查，不发 PUT")
    args = ap.parse_args()

    src = args.dist / "fr" / "index.html"
    if not src.exists():
        print(f"WARN: 源文件不存在 {src}（跳过 /fr/ 兜底）")
        return 2
    body = src.read_bytes()

    env = read_env(args.env)
    need = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    missing = [k for k in need if not env.get(k)]
    if missing:
        print(f"WARN: .env 缺 {', '.join(missing)}（跳过 /fr/ 兜底）")
        return 2

    if args.dry_run:
        print(f"[dry-run] 将 PUT r2:{env['R2_BUCKET']}/{KEY} ← {src}（{len(body):,} B）")
        return 0

    try:
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.credentials import Credentials
    except ImportError:
        print("WARN: 缺 botocore，无法签名（跳过 /fr/ 兜底）")
        return 2

    host = f"{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
    url = f"https://{host}/{env['R2_BUCKET']}/{KEY}"
    now = datetime.now(timezone.utc)
    req = AWSRequest(method="PUT", url=url, data=body, headers={
        "Host": host,
        "Content-Type": CONTENT_TYPE,
        "Content-Length": str(len(body)),
        "x-amz-content-sha256": hashlib.sha256(body).hexdigest(),
        "x-amz-date": now.strftime("%Y%m%dT%H%M%SZ"),
    })
    SigV4Auth(Credentials(env["R2_ACCESS_KEY_ID"], env["R2_SECRET_ACCESS_KEY"]),
              "s3", "auto").add_auth(req)
    prepared = req.prepare()
    request = urllib.request.Request(prepared.url, data=body, method="PUT",
                                     headers=dict(prepared.headers))
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            print(f"fr/ -> PUT {resp.status}（{len(body):,} B, {CONTENT_TYPE}）"
                  f"  # 临时兜底：Cloudflare 加第 5 条 Transform Rule 后可删")
            return 0
    except urllib.error.HTTPError as exc:
        detail = (exc.read() or b"")[:400].decode("utf-8", "replace")
        print(f"WARN: PUT fr/ 失败 HTTP {exc.code}：{detail}")
        return 1
    except Exception as exc:  # 网络错误等
        print(f"WARN: PUT fr/ 失败：{exc!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
