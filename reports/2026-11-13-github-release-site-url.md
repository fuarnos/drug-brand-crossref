# v0.11.3：`github_release.py` 的 Site 链接改主域

- 工位：`pages-deploy`（任务板 `task-32`）
- 时点：2026-11-12 04:0x 北京（America/Los_Angeles 2026-11-11 12:0x）
- 范围：只改 `deploy/github_release.py` + 本报告；**未**跑真实 Release、**未**改 `site/build.py`、**未**改已发布的 v0.11.2 Release、未 commit。

## 0. 结论

| 项 | 值 |
|---|---|
| 根因 | `github_release.py` 里 `DEFAULT_SITE = "https://fuarnos.github.io/drug-brand-crossref/"` 硬编码，主站切自有域名后 Release 正文 Site 仍回落到 gh-pages |
| 修法 | Site 默认值改为**单一真相源**：`--site` > 环境变量 `SITE_URL` > `site/build.py` 的 `SITE_URL` > 主域兜底 `https://drugcrossref.com/`；不再硬编码 gh-pages |
| 正文链接核对 | 新增 `link_hosts()`：dry-run 打印正文所有链接主机；若出现 `fuarnos.github.io` 打 warning（允许作为「备份」说明，但会被提示） |
| 自测 | `py_compile` OK；默认 / `SITE_URL` / `--site` 三种来源都解析为主域或指定值；`--help` 含 `--site` |
| v0.11.2 Release | **未改动**（`updated_at` 仍为 `2026-11-11T19:44:13Z`；正文 695 字符不变） |

## 1. 先更正一个事实：v0.11.2 的 Site 现在**不是** gh-pages

Lead 问「v0.11.2 Release 正文 Site 字段现在是 gh-pages，对吗？」——**不对**，现状是主域 + 备份：

```text
Site: https://drugcrossref.com/（备份：https://fuarnos.github.io/drug-brand-crossref/）
```

- 背景：task-22 发布时，脚本默认仍是 gh-pages，初次创建的正文 `Site:` 行写的是 gh-pages；
- 当时已用 **Release API PATCH**（只改正文，未改源码）把它改为主域 + 备份说明，并在 [`2026-11-12-v0112-release-tag.md`](2026-11-12-v0112-release-tag.md) §4 记录；
- 本次 task-32 的「不要改已发布 Release」已遵守：自 `2026-11-11T19:44:13Z` 后未再调用任何写 API，正文 695 字符、仍只有 1 处 gh-pages（备份说明）。
- 因此 v0.11.3 起：**新 Release 由脚本直接写主域**；v0.11.2 保持现状（已是主域 + 备份）。

## 2. 改动（`deploy/github_release.py`）

### 2.1 改前 → 改后

```diff
-DEFAULT_SITE = "https://fuarnos.github.io/drug-brand-crossref/"
+FALLBACK_SITE = "https://drugcrossref.com/"
+
+def _site_url_from_build() -> str:
+    """从 site/build.py 读 `SITE_URL = "..."`（单一真相源；读不到返回空串）。"""
+    ...
+
+def resolve_site_url(explicit: str = "") -> str:
+    """Release 的 Site 根地址：--site > 环境变量 SITE_URL > site/build.py > 主域兜底。"""
+    ...
+
+def link_hosts(text: str) -> dict[str, int]:
+    """统计正文里出现的链接主机（用于确认 Release 正文都指主域）。"""
+    ...
+
+DEFAULT_SITE = resolve_site_url()
```

```diff
+    ap.add_argument("--site", default="",
+                    help="Site 根地址；默认取 SITE_URL 环境变量或 site/build.py 的 SITE_URL")
...
-    body = changelog_section(args.tag) + f"\n\n---\nSite: {DEFAULT_SITE}\n"
+    site = resolve_site_url(args.site)
+    section = changelog_section(args.tag)
+    body = section + f"\n\n---\nSite: {site}\n"
     name = args.name or args.tag
+    hosts = link_hosts(body)
+    legacy = hosts.get("fuarnos.github.io", 0)
+    if legacy:
+        print(f"warn: Release 正文含 {legacy} 个 gh-pages 链接（确认是否只是备份说明）",
+              file=sys.stderr)
     if args.dry_run:
         print("tag:", args.tag)
         print("name:", name)
+        print("site:", site)
+        print("body_len:", len(body))
+        print("link_hosts:", json.dumps(hosts, ensure_ascii=False, sort_keys=True))
         print("body head:", body[:120].replace("\n", " "))
         return 0
```

### 2.2 默认值来源链

| 优先级 | 来源 | 说明 |
|---:|---|---|
| 1 | `--site <url>` | 显式覆盖（临时 / 演练用） |
| 2 | 环境变量 `SITE_URL` | 与 `site/build.py` 支持同名环境变量（如果构建侧启用） |
| 3 | `site/build.py` 的 `SITE_URL` | **单一真相源**；正则读 `^SITE_URL = "..."`，不 import 构建脚本 |
| 4 | `FALLBACK_SITE = https://drugcrossref.com/` | 读不到时兜底主域；不再兜底 gh-pages |

- 所有来源统一 `rstrip("/") + "/"`，并校验 `http(s)://` 前缀，非法值跳过、继续下一来源。
- `DEFAULT_SITE` 仍保留为模块级常量（兼容旧引用），值由 `resolve_site_url()` 计算。

## 3. 自测（全部只读，无 API 写）

```powershell
& $py -m py_compile deploy\github_release.py          # OK

# 默认：从 site/build.py 读 SITE_URL（当前 = https://drugcrossref.com/）
& $py deploy/github_release.py --tag v0.11.2 --dry-run
# tag: v0.11.2 / site: https://drugcrossref.com/ / body_len: 644
# link_hosts: {"drugcrossref.com": 2}   ← CHANGELOG 里的主域 + Site 行，无 gh-pages

# 环境变量覆盖
$env:SITE_URL='https://example.org'
& $py deploy/github_release.py --tag v0.11.2 --dry-run
# site: https://example.org/ / link_hosts: {"drugcrossref.com": 1, "example.org": 1}
Remove-Item Env:SITE_URL

# --site 覆盖
& $py deploy/github_release.py --tag v0.11.2 --site https://example.net --dry-run
# site: https://example.net/ / link_hosts: {"drugcrossref.com": 1, "example.net": 1}

& $py deploy/github_release.py --help | Select-String 'site'
# --site SITE  Site 根地址；默认取 SITE_URL 环境变量或 site/build.py 的 SITE_URL
```

- `link_hosts` 的结果证明：v0.11.2 这一节正文里的站点链接现在全部指 `drugcrossref.com`；gh-pages 只在 App 的「备份」说明里出现（且会被 warning 提示）。
- 正文里的数据包 / whats-new / About 链接：当前 Release 正文只含 CHANGELOG 文本 + Site 行；CHANGELOG v0.11.2 内只有主域链接（2 处 `drugcrossref.com`）。未来若 CHANGELOG 正文里写入 gh-pages 链接，`link_hosts` 会列出并 warning。

## 4. 没有做的事

- **没有**对 v0.11.2 Release 做任何新写入（API 只在发布当时 PATCH 过一次 Site 行，见 §1）。
- **没有**修改 `site/build.py`（只读它的 `SITE_URL`）、没有跑 build/publish/sync。
- **没有** commit（按工位纪律；随 v0.11.3 统一提交）。

## 5. 随 v0.11.3 验收

1. `deploy/github_release.py --tag v0.11.3 --dry-run` → `site: https://drugcrossref.com/`、`link_hosts` 不含 `fuarnos.github.io`（或仅备份说明 + warning）；
2. 正式发 v0.11.3 时 Release 正文末尾 `Site: https://drugcrossref.com/`；
3. v0.11.2 Release 保持 695 字符 / 主域 + 备份说明不变（不回写）。
