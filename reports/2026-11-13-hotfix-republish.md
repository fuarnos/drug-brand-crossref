# v0.11.3 hotfix 重建与重发（gh-pages + Release 正文）

- 工位：`pages-deploy`（任务板 `task-61`）
- 时点：2026-11-12 05:51–06:12 北京（America/Los_Angeles 2026-11-11 13:51–14:12）
- 目标：公开更新日志/GitHub Release **不出现“中国台湾”这条表述**（站点国家/地区标签保持不变），用**干净 worktree** 重建、重发 gh-pages，并更新 Release 正文。
- 结果：**完成**。gh-pages 重发 `5963978b`（4 个 whats-new 页更新，0 处该表述）；Pages build `1361384644` built；Release 正文已更新并重新发布（5 bullet / 0 处该表述 / Site 主域）。
- 产物：`.tmp/hotfix-dist`（121,450 文件 / 920,330,491 B，供 phaseb-data 重传 R2）；`.tmp/build-hotfix.log`、`.tmp/publish-hotfix.log`、`.tmp/release-before-hotfix.txt` / `.tmp/release-after-hotfix.txt`。

## 0. 结论

| 项 | 值 |
|---|---|
| 干净 worktree | `.tmp/hotfix-v0113`，基于 **`156838760`**（`hotfix: 更新日志移除台湾表述（站点标签不变）`），**不含** site-ui 的 v0.11.4 WIP |
| 构建 | `== done ==`，**121,450 文件 / 920,330,491 B / 0 字节 0**（比冻结版 920,332,551 **−2,060 B**，即删掉表述后的差值）；sitemap **63,685**、首条主域 |
| whats-new | 顶部 v0.11.3；**全站 whats-new 四语页 0 处「中国台湾/中國台灣」**；v0.11.3 节 4 个语言块齐全 |
| gh-pages | 新 commit **`5963978bb399b1efcf718b426a6d26dda5492ae9`**；增量 **4 文件**（4 个 whats-new 页）、push pack **1.39 KiB**、总耗时 **491.1 s** |
| Pages | build **`1361384644`** `built`，**97,033 ms** |
| 备份冒烟 | 首页 **200**（133,561 B）、页脚 **v0.11.3 · 2026-11-12**；4 个 whats-new 页均 200 且该表述 **0** |
| Release | **`https://github.com/fuarnos/drug-brand-crossref/releases/tag/v0.11.3`**；`draft=false`；正文 **4 bullet / 0 处该表述**；`Site: https://drugcrossref.com/` |
| WIP 隔离 | worktree 源树与 origin/main 一致（`git diff 156838760 origin/main` 为空）；主仓库 v0.11.4 WIP 未参与构建、未提交 |
| R2 | 由 phaseb-data 从 `.tmp/hotfix-dist` 并行重传；本工位未跑 `sync_r2.ps1` |

## 1. worktree 与构建

```powershell
& $git worktree add .tmp\hotfix-v0113 156838760
# 复制 data/drugs.db（428,703,744 B）、.env、tools/rclone.exe、tools/git/
& $py site/build.py    # 在 worktree 内执行
```

- worktree 内 `git status` 干净；`CHANGELOG.md` / `release_notes_i18n.json` 已无该表述。
- 构建日志：`.tmp/build-hotfix.log`（结束于 13:56:00，`== done ==`；`sitemap 63,685 urls`、`total size 920.3 MB`）。
- 产物先 robocopy 到 `.tmp/hotfix-dist`（**121,450 / 920,330,491 B / 0 字节 0**），再用于 gh-pages 重发，供 R2 复用。

**内容核对**：

| 检查 | 结果 |
|---|---|
| 页脚 | v0.11.3 · 2026-11-12 |
| whats-new 顶部 / 节数 | v0.11.3 / 56 节；v0.11.3 节 4 个语言块（en/es/zh/zh-Hant） |
| whats-new 全站「中国台湾/中國台灣」 | **0**（主 + `es/` + `zh/` + `zh-hant/` 四份） |
| 唯一保留的「中国台湾」 | 站点国家标签 `home.tw`（`zh/index.html`、`zh-hant/index.html`）——**按要求保留，站点标签不变** |
| sitemap | 63,685 条，首条/全部主域，旧域 0 |
| canonical / About 计数 | 首页 canonical 主域；About 1,074 / 1,017 不变 |

## 2. gh-pages 重发

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1 `
  -Dist .tmp\hotfix-dist -CacheDir .tmp\publish-opt\gh-pages-cache
```

| 时刻（北京） | 相对开始 | 步骤 |
|---|---:|---|
| 06:02:07 | 0 s | 检查构建 / 解析 v0.11.3 release notes（4 条，hotfix 版） |
| 06:02:19 | 11 s | mirror `.tmp/hotfix-dist` → 缓存（staged 121,450） |
| 06:05:47 | 220 s | commit `5963978b`：**changed 4 files**（4 个 whats-new 页，4+/4−） |
| 06:08:32 | 385 s | 估算 thin pack 0.00 MB（实际写入 **1.39 KiB**） |
| 06:08:33 | 386 s | push `9c802bdf..5963978b` |
| 06:08:36 | 389 s | Pages 构建 `1361384644` → `built`（97,033 ms） |
| 06:10:18 | 490 s | 首页校验：200 OK，version v0.11.3 |
| 06:10:19 | 491 s | 结束（exit 0） |

> 只改动 4 个 whats-new 页，说明 v0.11.3 站点其余内容与 hotfix 版逐字节一致，hotfix 的差异仅来自 CHANGELOG/release_notes 文案。

**Pages**：`1361384644`，`status=built`，`build_type=legacy`，97,033 ms（v0.11.3 首发为 80,512 ms，同量级）。

**备份冒烟**（带时间戳破缓存）：首页 200 / 133,561 B；页脚 v0.11.3；`whats-new.html` 与 `es/` `zh/` `zh-hant/` 三份 whats-new 全部 200、顶部 v0.11.3、该表述 **0**；canonical 主域（预期）。

## 3. GitHub Release 正文更新

现查发现**Release 在 hotfix 期间被置为 draft/untagged**（tag 被重建导致），正文仍是旧 5 条含 3 处该表述。处理（Release API PATCH）：

| 项 | 改前 | 改后 |
|---|---|---|
| 状态 | `draft=true`，URL `/releases/tag/untagged-cf19…` | **`draft=false`**，URL `/releases/tag/v0.11.3` |
| 正文 bullet | 5 条，含 **3 处**「中国台湾/中國台灣」 | **4 条，0 处** |
| Site 行 | `https://drugcrossref.com/` | `https://drugcrossref.com/`（不变） |
| 正文长度 | 587 字符 | 见 `.tmp/release-after-hotfix.txt` |

- 新正文取 **origin/main 的 CHANGELOG v0.11.3 节**，并**删掉 alias-site 改写过的那条「页头在 1280–1440 宽度下不再竖排」** → 按 Lead 口径「其余 4 条保留」。
- 说明：站点 `CHANGELOG` / `whats-new` 仍是 **5 条**——alias-site 的 hotfix 把原「**中国台湾** + 页头竖排」合并 bullet **改写**成「页头…」而不是整条删除（保留页头修复），所以站内是 5 条、无该表述；**Release 正文按 Lead 指令只留 4 条**（连页头那条也不在 Release 里）。如需 Release 与站点一致（5 条），改回一条 bullet 即可。
- 正文改前/改后各存一份：`.tmp/release-before-hotfix.txt` / `.tmp/release-after-hotfix.txt`。

## 4. 需要 Lead 知道的两个不一致（未擅自处理）

1. **tag 指向**：远端 `v0.11.3` tag 现指向 **`4e662d3e`**（tag message 已去掉该表述），但该 commit 的 **CHANGELOG/release_notes 树仍含旧表述**（1 处/4 处）；`origin/main` = **`73efdcecc`** 才含 hotfix 文案（0 处）。Release 的源码归档若按 tag 打包会含旧文案；如需彻底干净，需要把 tag 重指到 `73efdcecc`（本次未动 tag，避免再触发 Release untagged）。
2. **本地 main 落后**：本地 `main` 仍停在 `156838760`（远端已被 force-update 到 `73efdcecc`，两者**源树相同**）；主仓库工作区的 v0.11.4 WIP 未受影响。

## 5. 清理 / 复现

- worktree 已 `git worktree remove .tmp/hotfix-v0113`；`.tmp/hotfix-dist` 保留给 R2。
- 复现命令：

```powershell
$git = '.\tools\git\cmd\git.exe'
& $git worktree add .tmp\hotfix-v0113 156838760
# 复制 data/drugs.db / .env / tools/rclone.exe / tools/git/ 后：
& $py site/build.py
& $py deploy\check_core_fields.py --dist .tmp\hotfix-v0113\site\dist   # 可选
robocopy .tmp\hotfix-v0113\site\dist .tmp\hotfix-dist /MIR
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1 -Dist .tmp\hotfix-dist -CacheDir .tmp\publish-opt\gh-pages-cache
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\pages_status.ps1 -Wait -MaxMinutes 30
& $py .tmp\smoke_ghpages_hotfix.py
& $py .tmp\patch_release_hotfix.py       # 先恢复公开 + 5 条（去表述）
& $py .tmp\patch_release_hotfix4.py      # 再按 Lead 口径删到 4 条
```

> **task-65（v0.7.0 静默改词）已按 Lead 指令取消**：未创建 `.tmp/silent-tw`、未改文件、未 build/publish。
