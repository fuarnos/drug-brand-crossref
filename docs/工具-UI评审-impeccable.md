# 工具：UI 评审用 impeccable skill（用户级安装）

> 一句话：站点 UI 的「机械体检 + 设计评审」外挂，装在**用户级** DSH 技能目录，不进仓库、不进构建、不随发布走。
> 安装日期 2026-11-10；版本 skill **4.8.2** / engine **0.1.22**。

## 1. 装在哪、装了什么

| 项 | 值 |
|---|---|
| skill 目录 | `C:\Users\asus\.dsh\skills\impeccable`（22.8 MB，`SKILL.md` + `reference/` 42 个 + `scripts/`） |
| 引擎二进制 | `...\impeccable\scripts\bin\windows-x64\impeccable.exe`（21.7 MB） |
| 引擎校验 | sha256 `4bacf8c756ec3fda3b9fcb69bf1869d4d700ff471be1e31cbff669222dcd8ff2` = 上游 `engine-v0.1.22` 的 `impeccable-windows-x64.exe` |
| 来源 | `github.com/pbakaus/impeccable`（Apache-2.0），tarball 取自 `main` |
| 作用域 | 用户级 → 所有项目共用；本仓库 `.dsh/skills/` 只有 5 个项目技能，**没有被改动** |

引擎放在 launcher 认的「兄弟目录」里，所以 `.cmd` 启动时不联网、不下载、不碰 `~/.impeccable/`。

## 2. 怎么调用（Windows / PowerShell）

```powershell
$imp = "$env:USERPROFILE\.dsh\skills\impeccable\scripts\impeccable.cmd"

& $imp context                                  # 每会话跑一次，加载 PRODUCT.md / DESIGN.md
& $imp detect --json 'site\dist\index.html'     # 源码扫描（exit 0 干净 / 2 有 finding）
& $imp detect --json --viewport 390x844 http://127.0.0.1:8000/   # 渲染扫描（驱动本机 Chrome）
& $imp detect --list-rules --quiet              # 规则 id 全集
```

Agent 侧也可以直接 `skill` 工具加载 `impeccable`（本会话已出现在技能目录）。

## 3. 本机坑（踩过一次，别再踩）

- **schannel 系客户端连不上 GitHub**：`git.exe` / `curl.exe` 报 `schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS`。
  所以 `git clone` 与 launcher 的「首次运行自动下载引擎」都会失败。可行路径是 **node 的 fetch**（走 OpenSSL + 内置 CA）：
  `node -e "fetch(url)"` 正常 200。升级引擎时照此下载 + 校验 sha256，再覆盖兄弟目录里的 `impeccable.exe`。
- skill 目录里的 `scripts/impeccable`（sh 版）在本机没法用，一律走 `impeccable.cmd`。

## 4. 使用纪律（与本仓库规则对齐）

- **只用只读两招**：`critique`（设计评审）与 `audit`（技术体检）、`detect`（规则扫描）。
- **不开 `live` 模式**：它会在项目里起服务、写 `.impeccable/`，甚至调外部 agent，越过「只读评审」的边界。
- **不把 `.impeccable/` 提交进仓库**：它的 `PRODUCT.md` / `DESIGN.md` / `.impeccable/` 属于产品级上下文文件，
  一旦入库就得按 `AGENTS.md` §5 走全量建站 + 首屏守卫 + 三语同步。报告统一落 `reports/`（§8）。
- AI 味检测规则是**外部标准的机械映射**，不替代本仓库既有的 7 指标（AFCR / 主操作 / 条目数 / chrome / 悬浮 / 字号 / 横向溢出）：
  两者冲突时以 `docs/设计原则-按人能看到的来.md` 为准（那是本项目自己定的阈值）。
- 检测器**不判断**「能不能互换 / 剂量」这类内容问题，那是仓库红线，不归它管。

## 5. 相关文件

- 首次使用记录：[reports/2026-11-10-UI外挂与首页评审.md](2026-11-10-UI外挂与首页评审.md)
- 项目自带量尺：`deploy/first_screen_check.py`（`--viewports` / `--pages` / `--json` / `--shots`）
- 既有设计规范：[设计原则-按人能看到的来.md](设计原则-按人能看到的来.md)、[ui-overhaul-spec.md](ui-overhaul-spec.md)
