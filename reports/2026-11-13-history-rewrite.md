# git 历史与 tag 重写：移除提交信息/注释里的「中国台湾/台湾」

> 工位：search-alias · task-64 · 2026-11-13 · **破坏性操作（Lead 已批准）**
> 范围：只重写 `main` 与 tag `v0.11.3`；**未碰 `gh-pages`**；未改任何文件内容。

---

## 0. 结论先行

1. **远端 `main` 与 tag `v0.11.3` 已重写并推送完成**，`git log --all --grep='台湾'` = **0**，
   远端 194 条提交逐条走 GitHub API 扫描：**命中 0**。
2. 新 `main` = `73efdcecc59016d17a3c29f4977198134abb3fc9`；
   新 tag `v0.11.3` = `a30a4f9eb2f93e6cee623f42ada66858e2379532` → commit `4e662d3ed1ac1b5093f11ee5efc85d3a4def449c`。
3. **执行方式与任务书不同，原因是被 sandbox 挡住**（见 §2）：`git filter-branch` 与本地
   `git clone` 都需要 git 起 `sh`，而 `sh` 在本机无法创建管道（`couldn't create signal pipe, Win32 error 5`，
   与本会话里 Chrome/CDP、trilingual 的报错同源）。改用 **git plumbing 逐字节重建 commit 对象**，
   语义等价（只改 message / parent），且比 filter-branch 更精确：tree、author、committer、时间戳逐字节保留。
4. **一个必须让用户知道的事实**：GitHub 上**旧的两个 commit SHA 仍能按直接 URL 访问**
   （`/commits/156838760`、`/commits/ec1f40b01`，对象未被回收）。它们已不再被任何分支/tag 引用，
   正常浏览与 `git log` 看不到；但 GitHub 不会因 force-push 立刻回收不可达对象，
   客户端也无法强制清除。要彻底抹掉只能走 GitHub Support 或删库重建 —— 需用户决定，本轮未做。

---

## 1. 备份（可回滚）

| 项 | 路径 / 值 |
|---|---|
| bundle（`--all`，`git bundle verify` 通过：「完整历史」） | `.tmp/pre-rewrite-20261113.bundle`（80.6 MB） |
| 本地备份分支（**原仓库**保留） | `backup/pre-rewrite-20261113` → `15683876054f015c299cafc01caeb65da7b294f8` |
| 旧 main | `15683876054f015c299cafc01caeb65da7b294f8` |
| 旧 tag object / commit | `835c3580b356153eaab2e2a0563117a85d7a72bd` → `ec1f40b01da4c774f9aa797c64ea8733929943ae` |
| 旧 gh-pages（未动） | `9c802bdfba26fb838681b81ae916967a01f4e5f6` |

旧 SHA 机器可读副本：`.tmp/pre-rewrite-shas.json`。

---

## 2. 为什么没用 `filter-branch`

| 尝试 | 结果 |
|---|---|
| `git clone --no-hardlinks <本地路径> .tmp/rewrite-clone` | **失败**：`sh.exe: fatal error - couldn't create signal pipe, Win32 error 5` |
| `git filter-branch -f --msg-filter 'cat' -- _probe`（丢弃分支上试探） | **失败**：同一个 `sh` 报错，exit 66 |

因此改为：
1. **复制 `.git` 到 `.tmp/rewrite-clone`**（`Copy-Item`，非硬链接；主工作区完全不受影响）；
2. 用 `git cat-file commit` 取原始对象字节 → 只替换 `parent` 行与 message → `git hash-object -t commit -w --stdin` 写回；
3. 用 `git update-ref` 把 `main` 指到新链头，重建 annotated tag。

脚本：`.tmp/rewrite_history.py`。这一步同时把主仓库的 linked worktree 元数据（`.tmp/hotfix-v0113`）
从克隆副本里摘掉（`worktrees/hotfix-v0113` 的 HEAD 仍指向旧提交，会让 `--all` 一直扫到旧历史）；
**原仓库的 worktree 及其 HEAD 完全没动**。

---

## 3. 旧 → 新 SHA 对照

| 对象 | 旧 | 新 |
|---|---|---|
| `main`（tip） | `15683876054f015c299cafc01caeb65da7b294f8` | **`73efdcecc59016d17a3c29f4977198134abb3fc9`** |
| hotfix 提交 | `156838760` | `73efdcecc` |
| docs 收尾提交 | `b13dce72842b790d8be1980631616e42568520d7` | `41360a662a488b45d06c2d087e93cb5a374f8b47` |
| v0.11.3 源码提交 | `ec1f40b01da4c774f9aa797c64ea8733929943ae` | `4e662d3ed1ac1b5093f11ee5efc85d3a4def449c` |
| tag `v0.11.3`（annotated object） | `835c3580b356153eaab2e2a0563117a85d7a72bd` | `a30a4f9eb2f93e6cee623f42ada66858e2379532` |

只重建了尾部 3 个提交（另 191 个提交无 message 变化且父提交未变，SHA 保持原样）。

### message 对照

| 提交 | 改前 | 改后 |
|---|---|---|
| v0.11.3 源码 | `v0.11.3: 无商品名显示厂家/中国台湾/页头竖排/剂型突出/ATC 卡片等高折叠/whats-new 四语/占位符守卫` | `v0.11.3: 无商品名显示厂家/页头竖排/剂型突出/ATC 卡片等高折叠/whats-new 四语/占位符守卫` |
| hotfix | `hotfix: 更新日志移除台湾表述（站点标签不变）` | `hotfix: 更新日志文案修正（站点标签不变）` |
| tag 注释 | `v0.11.3 - 无商品名显示厂家 + 中国台湾 + 页头/剂型/ATC 卡片 + whats-new 四语` | `v0.11.3 - 无商品名显示厂家 + 页头/剂型/ATC 卡片 + whats-new 四语` |

两条提交的正文（`%B`）都是单行，没有额外正文需要清理；全仓仅这 2 条提交命中「台湾」。
「台灣 / 臺灣」变体：0 条。

### 内容零改动

`git diff-tree` 对比新旧对象：三个提交的 **tree 完全相同**（无任何输出）；
author / committer / 邮箱 / 时间戳逐字一致（脚本内断言为 `True`）。
即**只改了提交信息与 tag 注释，代码与站点内容一字未动**。

---

## 4. 推送结果

在主工作区之外的 `.tmp/rewrite-clone` 里执行，凭据走 `.env` 的 `GITHUB_TOKEN`
（`http.extraHeader` + openssl 后端，与 `deploy/publish.ps1` 同一套做法；token 未出现在日志/命令行）。

```
+ 156838760...73efdcecc main -> main (forced update)
- [deleted]             v0.11.3
* [new tag]             v0.11.3 -> v0.11.3
```

- 第一条用 `--force-with-lease=refs/heads/main:156838760...`，租约校验通过才覆盖，防误伤。
- 只推了 `refs/heads/main` 与 `refs/tags/v0.11.3` 两个 refspec；**`gh-pages` 与其余 tag 未推、未动**。

---

## 5. 验证结果

| 验证项 | 结果 |
|---|---|
| 克隆内 `git log --all --grep='台湾'` | **0** |
| 克隆内 `git log --all --grep='中国台湾'` | **0** |
| 远端 `refs/heads/main` | `73efdcecc59016d17a3c29f4977198134abb3fc9`（= 本地一致） |
| 远端 `refs/tags/v0.11.3` | `a30a4f9eb2f93e6cee623f42ada66858e2379532`（deref → `4e662d3e…`，= 本地一致） |
| 远端 main 上 `--grep='台湾'` | **0** |
| GitHub API 全量扫描 main 历史 | 194 条提交，**命中 0** |
| GitHub API tag 注释 | `v0.11.3 - 无商品名显示厂家 + 页头/剂型/ATC 卡片 + whats-new 四语`（干净） |
| `gh-pages` | `9c802bdfba26fb838681b81ae916967a01f4e5f6`（与发布前一致，**未被触碰**） |
| 旧 SHA 直接访问 | ⚠️ **仍可访问**：`/commits/156838760`、`/commits/ec1f40b01` 仍返回原文（见 §0.4） |

---

## 6. 回滚步骤

任一步出错时的恢复路径（按代价从低到高）：

```powershell
$git = '.\tools\git\cmd\git.exe'

# 1) 只回滚本地引用（远端还没动）
& $git update-ref refs/heads/main 15683876054f015c299cafc01caeb65da7b294f8
& $git tag -d v0.11.3
& $git tag -a v0.11.3 -m "v0.11.3 - 无商品名显示厂家 + 中国台湾 + 页头/剂型/ATC 卡片 + whats-new 四语" ec1f40b01

# 2) 远端已推送但需要回退：把旧 SHA 重新推回去（force）
& $git push --force-with-lease=refs/heads/main:73efdcecc59016d17a3c29f4977198134abb3fc9 origin 15683876054f015c299cafc01caeb65da7b294f8:refs/heads/main
& $git push origin :refs/tags/v0.11.3
& $git push origin 835c3580b356153eaab2e2a0563117a85d7a72bd:refs/tags/v0.11.3

# 3) 极端情况（本地仓库也损坏）：从 bundle 恢复
& $git clone .tmp\pre-rewrite-20261113.bundle restored
# 或：& $git fetch .tmp\pre-rewrite-20261113.bundle 'refs/*:refs/restored/*'
```

备份分支 `backup/pre-rewrite-20261113` 仍在**原仓库**（未推送、未删除），指向旧 main，
是最快的回滚锚点。`.tmp/rewrite-clone` 保留着旧对象，可随时 `git log 156838760` 复现旧历史。

---

## 7. 遗留与建议

1. **旧 SHA 仍可按 URL 访问**（§0.4）。要真正彻底，只有两条路：
   - 向 GitHub Support 提交请求，要求 GC 指定 SHA 的不可达对象；
   - 或删库重建（代价大，不建议）。
   目前状态下：任何人**正常浏览仓库、看分支/tag 列表、clone、`git log`** 都不会遇到该字样；
   只有拿着旧 SHA 直接拼 URL 才看得到。
2. **另一个未处理项（超出本任务范围，需你定）**：`88a047c10`（v0.7.0）的提交信息是
   `v0.7.0: Taiwan market (TFDA) + zh-Hant UI + TW matrix column + OGDL attribution` ——
   英文 `Taiwan`。它是已发布的 tag `v0.7.0` 历史，权限上也不在「只改 main 与 v0.11.3」范围内，
   本轮**未动**。若也要处理，等同再重写一次历史并强制推所有受影响 tag，需单独批准。
3. **原仓库本地 `main` 仍是旧 SHA** `156838760`（本轮没动主工作区，hotfix 构建还在用其 worktree）。
   之后在主仓库 `git pull`/`fetch` 会更新；从旧本地 main 直接 `git push` 会被远端拒绝（非快进），
   不会把旧历史推回去 —— 但建议尽快在主仓库跑一次 `git fetch origin && git reset --hard origin/main`
   或 `git pull --ff-only`（注意工作区有未提交改动，**先 stash**），避免后续有人误操作。
4. `.tmp/rewrite-clone`（约 242 MB）与 `.tmp/pre-rewrite-20261113.bundle`（80.6 MB）确认无误后可删；
   建议至少保留 bundle 到 v0.11.3 发布完成之后。
