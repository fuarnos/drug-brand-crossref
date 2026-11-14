# DSH「药品站」预设重启后消失：原因与恢复（2026-11-09）

## 结论

预设本身没坏，是 **profile 的 bundle 列表被桌面端的崩溃自愈机制重置了**：

1. `药品站` 预设是以 profile bundle（`@local/drug-preset`，`link:D:\同种药物商品名剂量对应网站\.dsh\preset-drug`）的形式安装的。
   bundle 只有在 `~/.dsh/profiles/desktop/package.json` 的 `dsh.profile.bundles` 里才会被加载；
2. 2026-11-09 20:01:50 和 20:02:00 两次 web boot 崩溃（`@deepseek-ai/dsh-message-quotes: failed`）；
3. 崩溃后桌面端执行 `sanitizeProfile`：把 `cordis.patch.yml` 改名成 `.bak-<时间戳>`，把 `dsh.profile.bundles`
   写回最小恢复集 `[dsh-base, dsh-web-app]`。于是药品站预设、windows-toast、引号插件、experimental 系列
   全部从列表里消失，profile 补丁里的 `agent-preset-registry.selectedDefault: drug` 也一起丢了。

2026-11-07 01:44 / 01:45 也发生过同一崩溃、同一次清空。所以观感是「每次重启预设就没了」——实际是
「每次启用某个会崩的第三方插件 → 下次启动崩 → 自愈清空」。

## 证据

| 事实 | 证据 |
|---|---|
| bundle 被摘掉 | `package.json` 的 `dsh.profile.bundles` 只剩 `dsh-base`、`dsh-web-app`；`plugin_manager list_bundles` 里 `@local/drug-preset` 为 `enabled:false` |
| 崩溃 | `%APPDATA%\@deepseek-ai\dsh-desktop\logs\crash-2026-11-10T04-01-50-011Z-web-boot.log`、`crash-2026-11-10T04-02-00-486Z-web-boot.log`：`web boot: 1 entry did not activate / @deepseek-ai/dsh-message-quotes: failed`；11-07 同款两份 |
| 自愈清空 | `cordis.patch.yml.bak-1794283338417`（= 2026-11-09 20:02:18）与 `package.json` 的 mtime 20:02:18 对齐；备份里还留着 `selectedDefault: drug`，当前文件已没有 |
| 时间线 | 12:08 启用 `@local/drug-preset`（plugin-operations 记录）→ 12:41 批量启用 9 个 bundle（含 `dsh-quote-to-composer@0.9.2`）→ 20:01/20:02 崩溃 → 20:02:18 自愈清空 |

## 最可能的触发者：dsh-quote-to-composer 0.9.2

- 它的 `package.json` 声明 `dsh.client.immediately: true`，客户端插件会**先于**内置插件加载；
- 它的 `client.js` 注册 `conversation.user.text.node` 槽位：
  `ctx.slots.inject('conversation.user.text.node', () => ctx.slots.register({ name: 'conversation.user.text.node', ... }))`；
- 0.2.2 的内置 `@deepseek-ai/dsh-message-quotes/client.js` 也 `ctx.slots.register({ name: "conversation.user.text.node" })`；
- 同槽位重复声明 → 后注册的一方 `ctx.effect` 抛错 → 该条目未激活 → boot 判定失败。因为第三方先加载，
  撞掉的是内置的 `message-quotes`，与日志完全吻合。
- 该插件 2026-10-27 21:23 安装（早于 11-07 与 11-09 两次崩溃）；崩溃后它被自愈禁用，所以之后启动都正常。

判定：**保持禁用**。若再启用后下一次重启仍以 `message-quotes: failed` 崩溃，即为此因，需作者适配 0.2.2
（或改注入方式，不再重复声明槽位）。

## 已做的恢复（2026-11-09 20:16–20:17）

1. 备份：`~/.dsh/profiles/desktop/package.json.manual-bak-20261109-201641`、`cordis.patch.yml.manual-bak-20261109-201641`；
2. `plugin_manager set_bundle @local/drug-preset enabled=true` → `changed: true, application: applied`，
   `dsh.profile.bundles` 已含该 bundle；live 树里 `include:preset-drug` 已出现（Config.listConfigs 5 条预设：standard/ptc/minimal/cordis/drug）；
3. `cordis.patch.yml` 末尾补回：

   ```yaml
   - id: agent-preset-registry
     name: "@deepseek-ai/dsh-agent-preset-registry"
     config:
       default: standard
       selectedDefault: drug
   ```

   用 js-yaml 解析校验通过（6 行，末行即该 override），写入后无新崩溃日志。

## 仍未恢复 / 待定

- `mcp-browser`（Playwright MCP，给会话加 `mcp__browser__*`）与 `plugin-market` 的 indexes 在同一次清空里丢失。
  两个路径都还在（`dsh-runtimes\...\node\bin\node.exe`、`default-workspace\node_modules\@playwright\mcp\cli.js`），
  需要时可按 12:41 备份里的原文补回。
- `dsh-quote-to-composer` 已于 2026-11-09 20:22 **卸载**（`remove_bundle`：pnpm 已移除依赖，profile 的
  `dependencies` 与 `dsh.profile.bundles` 都不再有它）——这是本次崩溃的唯一嫌疑源，直接拿掉。
- 其他被清掉的 experimental bundle（agent-team、inspector、session-search、tool-worktree、auto-review、
  session-titles）同样保持禁用，未恢复。`@local/windows-toast` 保留但禁用（纯 Host 插件，不注册任何客户端
  槽位，与 `message-quotes` 失败无关）。
- 计划任务形式的「自动修复」**没有装**（用户选择直接移除崩溃源）。修复脚本保留为手动工具，见下。

## 手动修复工具

`.dsh/dsh-preset-repair.ps1`（幂等、只补缺失、改动前 `.repair-bak-<时间戳>` 备份，UTF-8 BOM + PS 5.1 兼容）：

```powershell
# 检查（不写文件）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .dsh\dsh-preset-repair.ps1 -DryRun

# 真的修
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .dsh\dsh-preset-repair.ps1
```

它做三件事：bundles 缺 `@local/drug-preset` 就补；补丁缺 `agent-preset-registry` 行就补（`selectedDefault: drug`）；
`node_modules\@local\drug-preset` 链接丢了就按 `link:` 重建 junction。已在临时 profile 上验证「缺 → 补 → 再跑无改动」，
生成的 YAML 用 js-yaml 解析通过；对真实 profile 跑 `-DryRun` 输出「无需修复」。

## 防复发

- 第三方 / experimental bundle **一次只加一个**，加完立刻重启验证；崩过一次就先回退。
- 只要 web boot 崩一次，profile 就会被清空（bundle 列表 + 用户补丁），不是预设本身的问题；
  每次大改前把 `~/.dsh/profiles/desktop/{package.json,cordis.patch.yml}` 复制一份，恢复只需照抄两个字段。
- 本次事故的两份现场文件（`.bak-1794283338417`、`.bak-1794015952901`）建议保留，别清理。
- 下一次重启若仍崩，看 `%APPDATA%\@deepseek-ai\dsh-desktop\logs\crash-*-web-boot.log` 里新的 `xxx: failed`，
  那个 `xxx` 就是新的元凶，卸掉或回退它即可。
