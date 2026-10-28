# GoatCounter 访问分析 — 2026-10-29

> 数据源：GoatCounter API v0（`drug-brand-crossref.goatcounter.com`）· 区间 `2026-10-25T00:00:00Z` → `2026-10-30T00:00:00Z` · token 打码 `qsea…6oyc` · 生成于 2026-10-28T20:02:03+00:00

## 结论（先看这里）

- **俄罗斯流量：单次/低频访问、路径是正常站点路由（非扫描路径）、Linux + Chrome + 小视口（tablet 档，常见无头浏览器 800×600）且无后续浏览——更像**爬虫/预览机器人或 VPN/代理单次访问**，不是可识别的真实用户使用行为；小视口进一步支持无头浏览器特征**（置信度：中高）。RU 命中 1 次，占全部 47 次记录的 2.1%。
- 定位到候选路径：`/drug-brand-crossref`（该路径共 3 次；系统 {'Windows': 2, 'Linux': 1}；浏览器 {'Chrome': 3}；尺寸 {'tablet': 1, 'desktop': 2}）。
- **总记录 47**：页面浏览量 31 + 事件 16；活跃 3 天。
- 流量以美国（US）为主，浏览器 100% Chrome；无异常扫描路径。

## 数据总览

| 指标 | 数值 |
|---|---|
| 总记录（含事件） | 47 |
| 页面浏览量 PV | 31 |
| 事件数 | 16 |
| 活跃天数 | 3 |
| 国家 | US 46, RU 1 |
| 浏览器 | Chrome 47 |
| 系统 | Windows 46, Linux 1 |
| 屏幕档位 | tablet 1, desktop 46 |

### 每日访问

| 日期 | 记录数 |
|---|---|
| 2026-10-27 | 14 |
| 2026-10-28 | 23 |
| 2026-10-29 | 10 |

## Top 页面

| # | 路径 | 次数 | 事件? |
|---|---|---|---|
| 1 | `/drug-brand-crossref` | 3 | 否 |
| 2 | `/drug-brand-crossref/drug/acetaminophen.html` | 2 | 否 |
| 3 | `/drug-brand-crossref/es` | 2 | 否 |
| 4 | `/drug-brand-crossref/index.html?lang=zh` | 2 | 否 |
| 5 | `/drug-brand-crossref/whats-new.html` | 2 | 否 |
| 6 | `/drug-brand-crossref/?q=Excedrin+Extra+Strength` | 1 | 否 |
| 7 | `/drug-brand-crossref/about.html` | 1 | 否 |
| 8 | `/drug-brand-crossref/about.html?lang=en` | 1 | 否 |
| 9 | `/drug-brand-crossref/about.html?lang=es` | 1 | 否 |
| 10 | `/drug-brand-crossref/about.html?lang=zh` | 1 | 否 |
| 11 | `/drug-brand-crossref/combo/acetaminophen+chlorphenamine+dextromethorphan+pseudoephedrine.html` | 1 | 否 |
| 12 | `/drug-brand-crossref/confused.html` | 1 | 否 |
| 13 | `/drug-brand-crossref/drug/cetirizine.html` | 1 | 否 |
| 14 | `/drug-brand-crossref/es/?q=Excedrin+Extra+Strength` | 1 | 否 |
| 15 | `/drug-brand-crossref/index.html` | 1 | 否 |
| 16 | `/drug-brand-crossref/name/excedrin-extra-strength-pain-reliever.html` | 1 | 否 |
| 17 | `/drug-brand-crossref/warn.html` | 1 | 否 |
| 18 | `/drug-brand-crossref/warn.html?lang=en` | 1 | 否 |
| 19 | `/drug-brand-crossref/warn.html?lang=es` | 1 | 否 |
| 20 | `/drug-brand-crossref/warn.html?lang=zh` | 1 | 否 |

## 搜索事件（search-*）

| 搜索词事件 | 次数 |
|---|---|
| `search-cetirizine` | 1 |
| `search-cetirizine cetirizine` | 1 |
| `search-excedrin extra strength` | 1 |
| `search-左旋盐酸` | 1 |
| `search-左西替利嗪` | 1 |
| `search-泰诺` | 1 |
| `search-盐酸xi'ti'li'q` | 1 |
| `search-盐酸左旋` | 1 |
| `search-盐酸左旋西` | 1 |
| `search-盐酸西` | 1 |

**零结果事件**：当前站点 JS 未埋点 `search0-*` 事件（代码只有 `search-<term>`、`click-*`、`country-*`），因此本报告无法统计零结果；建议补埋点后纳入。

## 来源（referrer）

| 来源 | 次数 | 类型 |
|---|---|---|
| `(无来源)` | 13 | o |
| `fuarnos.github.io/drug-brand-crossref/index.html` | 7 | h |
| `fuarnos.github.io/drug-brand-crossref/warn.html` | 5 | h |
| `fuarnos.github.io/drug-brand-crossref/zh` | 4 | h |
| `fuarnos.github.io/drug-brand-crossref/whats-new.html` | 4 | h |
| `fuarnos.github.io/drug-brand-crossref` | 3 | h |
| `fuarnos.github.io/drug-brand-crossref/about.html` | 3 | h |
| `fuarnos.github.io/drug-brand-crossref/zh/index.html` | 3 | h |
| `github.com/fuarnos/drug-brand-crossref/deployments/github-pages` | 2 | h |
| `weixin110.qq.com` | 1 | h |
| `fuarnos.github.io/drug-brand-crossref/es` | 1 | h |
| `fuarnos.github.io/drug-brand-crossref/confused.html` | 1 | h |

## 俄罗斯流量排查

**结论：单次/低频访问、路径是正常站点路由（非扫描路径）、Linux + Chrome + 小视口（tablet 档，常见无头浏览器 800×600）且无后续浏览——更像**爬虫/预览机器人或 VPN/代理单次访问**，不是可识别的真实用户使用行为；小视口进一步支持无头浏览器特征**（置信度 中高）

| 证据 | 值 |
|---|---|
| 国家维度 | RU 1 次（占 2.1%） |
| 候选路径 | `/drug-brand-crossref`（共 3 次） |
| 系统 | {"Windows": 2, "Linux": 1} |
| 浏览器 | {"Chrome": 3} |
| 屏幕档位 | {"tablet": 1, "desktop": 2} |
| 来源 | [{"name": "", "count": 2, "scheme": "o"}, {"name": "github.com/fuarnos/drug-brand-crossref/deployments/github-pages", "count": 1, "scheme": "h"}] |
| 扫描器特征路径 | 无（路径均为正常站点路由） |

### 局限与建议

- GoatCounter API 不提供 UA/IP/ASN；CSV export 需 export 权限（本 token 403），无法做原始 hit 级交叉表
- 国家/浏览器/系统等维度按 GoatCounter 统计口径（含事件、按访问者计），与 PV 不完全等价
- 站点挂在 GitHub Pages，无服务端日志；如需 100% 确证需 Cloudflare/服务端访问日志或 GoatCounter 后台查看 UA

建议：
- 按机器人/噪音流量忽略即可，不需要封禁（本站无登录/写接口，无风险面）
- 自测流量建议在 GoatCounter 后台设置 skip-dev（按 UA/IP 排除），避免污染统计
- 如后续要监控异常，可给站点加 Cloudflare（免费版）看 ASN/UA，或在 GoatCounter 后台加 Bot 过滤
- 搜索零结果事件目前未埋点（代码只有 search-<term> / click-*），建议补 search0-<term> 事件后纳入本报告

## 复现

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
& $py deploy/analytics_report.py --start 2026-10-25T00:00:00Z --end 2026-10-30T00:00:00Z
```

_token 打码：`qsea…6oyc`；本报告不含 token 明文。_
