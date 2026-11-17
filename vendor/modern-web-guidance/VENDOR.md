# Modern Web Guidance（离线存档）

> 一句话：Google Chrome 团队主导、Microsoft Edge / Mozilla Firefox / MDN 共同维护的「前端最佳实践」agent 技能包，**原样存档**在此，供本仓 agent 离线检索。
> **不参与站点构建**：`site/build.py` 不读这个目录，产物里没有它的任何文件，也不是 npm / Python 依赖。

- 用户 2026-11-17 原话：「Google 开源了一个写前端的 Modena web gaidance」= **Modern Web Guidance**。
- 需求口径同日当场缩小为「**只负责把这个东西找到、保存**」——所以这里只做存档 + 用法说明，不做评估、不试点、不接构建链。

## 1. 来源与版本（可核验）

| 项 | 值 |
|---|---|
| 官方文档 | https://developer.chrome.com/docs/modern-web-guidance |
| 源码仓库 | https://github.com/GoogleChrome/modern-web-guidance-src |
| npm 包 | `modern-web-guidance@1.0.1`（**v1.0 于 2026-11-10 发布**） |
| npm tarball | https://registry.npmjs.org/modern-web-guidance/-/modern-web-guidance-1.0.1.tgz |
| tarball sha256 | `713d3d344d6fad5c9267fb1ed8daff5dd72df4634e9ad6b2bd3b0ca17f8438a3` |
| npm shasum (sha1) | `06a05ddadd0f87f29881b16705faf55c2a5dc83a` |
| npm integrity | `sha512-5ztUh5F1p2PewnSkA6EhsGUXqomaZY9qe6iWJCU4JbIQxHTky7s5lMJcPE4EbD1uhbQZIhl0HROH0+s6fIiGzg==` |
| license | **Apache-2.0**（全文见 `LICENSE`；第三方声明见 `THIRD_PARTY_NOTICES`） |
| 体积 | tarball **8,878,299 B** → 解包 **16,720,506 B / 281 文件**（与 npm 元数据一致） |
| 抓取 | 2026-11-17，Lead：`Invoke-WebRequest` 直取 tarball → 校验 sha1 → `tar -xzf` → robocopy 到本目录 |

## 2. 内容地图

```
vendor/modern-web-guidance/
├── VENDOR.md                    # 本文件
├── LICENSE                      # Apache-2.0 全文
├── THIRD_PARTY_NOTICES          # 上游第三方声明
├── README.md                    # 110 KB，含「262 个现代 Web 特性」全表与安装/用法
├── package.json                 # bin: modern-web-guidance → skills/modern-web-guidance/modern-web.mjs
├── skills/
│   ├── modern-web-guidance/
│   │   ├── SKILL.md             # 技能入口（frontmatter + 工作流：search → retrieve）
│   │   ├── modern-web.mjs       # CLI：search / list / retrieve / legacy-scan / install / uninstall / update
│   │   ├── search.mjs(+.map)    # 检索实现（本地索引，离线可用）
│   │   ├── legacy-scan.mjs      # 旧模式静态扫描（5.1 MB，含规则库）
│   │   ├── gen/                 # 检索索引（guides.json / guide-chunks.* / query-words.*）
│   │   ├── guides/              # **210 篇指南 md（2.0 MB）**，按 accessibility / css / ui-behaviors / ui-components / user-experience / visual-design / performance / wasm / webmcp 等分类
│   │   └── watchdog/            # 更新守卫
│   └── chrome-extensions/       # 25 文件 122 KB，Chrome 扩展相关参考（原样保留）
├── .agents/ .claude-plugin/ .codex-plugin/ .cursor-plugin/ .grok-plugin/
├── plugin.json  gemini-extension.json  kimi.plugin.json   # 各家 agent 的插件清单，原样保留便于看官方安装形态
├── assets/  policies/
└── .github/                     # 上游仓库的协作文档（16 KB）
```

指南覆盖（README「262 features」）：CSS 与布局 140 · HTML/DOM 37 · JS 与 API 85，另有 ui-components / ui-behaviors / accessibility / performance / visual-design / forms / built-in AI / wasm / webmcp 等专题。

## 3. 离线用法（不联网、不上报）

```powershell
$node = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe'
$mwg  = 'vendor\modern-web-guidance\skills\modern-web-guidance\modern-web.mjs'
$env:DISABLE_TELEMETRY = '1'    # 官方默认匿名上报使用信息，本仓一律关掉

& $node $mwg search "light dismiss dialog"                 # 找指南（返回 id + description）
& $node $mwg list                                           # 全部 use case
& $node $mwg retrieve "dialog,light-dismiss-a-dialog"       # 取指南正文（逗号分隔多 id）
& $node $mwg legacy-scan site\build.py                      # 扫「旧模式」并给现代化建议
```

- `search` / `list` / `retrieve` / `legacy-scan` 只读本地 `gen/` 与 `guides/`，**不需要网络**（2026-11-17 实测：断网无关，未发起网络请求；但请保持 `DISABLE_TELEMETRY=1`）。
- `install` / `update` 会去 npm 拉包并写入 agent 目录（`.claude/skills`、`.agents` 等），**在本仓不要跑**——会污染工作树，且本仓不用 npm 构建链。
- 需要 Node ≥ 22（本机 v24.21.0，满足）。

## 4. 升级方式

```powershell
$m = Invoke-RestMethod 'https://registry.npmjs.org/modern-web-guidance/latest'
$m.version; $m.dist.tarball; $m.dist.shasum        # 先看版本与哈希
# 下载新 tarball → 校验 → tar -xzf 到 .tmp → robocopy 覆盖本目录（保留 VENDOR.md 并更新下表）
```

升级时请同时更新本文 §1 的版本 / 哈希 / 体积与日期，并在 `CHANGELOG.md` 留一行（存档更新也走同一套口径：数字现查、不照抄）。

## 5. 许可与边界

- **Apache-2.0**：`LICENSE` 与 `THIRD_PARTY_NOTICES` 原样保留；本仓只作内部开发参考，不分发修改版。
- **不是依赖**：不进 `site/build.py`、不进 `data/`、不进 CI 安装步骤、不写进 `site/dist`（站点仍是「无 npm / 静态构建 / 内联资源」）。
- 使用边界同 `AGENTS.md` §1：只用于校准前端实现（dialog / popover / 表格 / 滚动 / 性能 / 无障碍 / 排版 / 表单），**不给用药建议、不做剂量换算、不判断可替代**。
