# R2 + 自定义域上线评估（2026-11-11，v0.11.0 之后）

- 工位：`pages-deploy`（任务板 `task-8`）
- 前置：v0.11.0 已上 gh-pages（`6946d8e42`，`verify_live` 0 failures，见 [`reports/v0110-release-r2-20261111.md`](v0110-release-r2-20261111.md)）
- 执行时间：2026-11-10 11:38–11:41（America/Los_Angeles；北京时间 2026-11-11 03:38–03:41）
- 纪律：未打印/未提交任何凭证；未改 `.env`；**未向 R2 写入任何对象**（没跑 sync）；gh-pages 保持线上

## 结论先行

**未切到新域名。卡点不在域名绑定，在 R2 凭证：`.env` 的 `R2_SECRET_ACCESS_KEY` 只有 62 位十六进制，R2 的 Secret Access Key 是 64 位十六进制，签名必然对不上（`403 SignatureDoesNotMatch`）。**

| 项 | 结果 |
|---|---|
| R2 连通性 | **FAIL**：`rclone lsf/size/check` 全部 `403 SignatureDoesNotMatch`（ListObjectsV2） |
| 能否看到 bucket 内容 | **不能**（列桶本身就失败）；无法确认对象数 / 总字节 |
| 自定义域绑定 | 用户面板截图显示 `drugcrossref.com` **Active / Access Enabled**；但 `https://drugcrossref.com/` 仍 **404 / server: cloudflare**，与「桶里没有内容」一致，无法用 HTTP 反证绑定 |
| 是否已同步 | **否**。`site/dist` 898 MB / 121,450 文件一个字节都没上传，桶未被本次操作改动 |
| gh-pages 主线 | 不受影响，v0.11.0 正常（`https://fuarnos.github.io/drug-brand-crossref/`） |
| 成本 | 仍是 **0 元**（本轮没有上传，无 Class A 消耗） |

## 1. 现场证据（只读，数字现查）

执行命令（凭证只进临时 `%TEMP%\rclone-r2-*.conf`，命令结束即删）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1 -CheckOnly
# 等价 rclone：rclone lsf r2:drug-brand-crossref --config <temp> --fast-list
#              rclone size r2:drug-brand-crossref --config <temp> --fast-list --json
```

| 调用 | 结果 |
|---|---|
| `rclone lsd r2:` | `403 AccessDenied`（ListBuckets）——R2 API token 默认无 ListBuckets 权限，**正常** |
| `rclone lsf r2:drug-brand-crossref --fast-list` | `403 SignatureDoesNotMatch`（ListObjectsV2） |
| `rclone size r2:drug-brand-crossref --fast-list` | `403 SignatureDoesNotMatch`（ListObjectsV2） |
| `deploy/sync_r2.ps1 -CheckOnly` | **exit 1**；`NOTICE: Failed to check with 17 errors: … SignatureDoesNotMatch`；日志 `.tmp/release-v0110-r2/r2-checkonly.log` |
| rclone 版本 | v1.76.0（Windows 11，`tools\rclone.exe` 就位） |

> 注意：`check` 输出里那些 `ERROR : index.html: file not in S3 bucket` **不是**「桶是空的」的证据——它是目标列表失败后 rclone 对每个源文件的兜底报错，末行明确是 `Failed to check … ListObjectsV2 … SignatureDoesNotMatch`。**不能据此断言空桶**。

## 2. 根因：Secret Access Key 长度不对

只查值的形状（不打印内容）：

| `.env` 键 | 长度 | 形状 | 判断 |
|---|---:|---|---|
| `R2_ACCOUNT_ID` | 32 | 全十六进制 | 正常（R2 account id = 32 hex） |
| `R2_ACCESS_KEY_ID` | 32 | 全十六进制 | 正常（R2 access key id = 32 hex） |
| `R2_SECRET_ACCESS_KEY` | **62** | 全十六进制 | **异常：R2 secret access key 是 64 hex**（[Cloudflare R2 密钥形状参考](https://pkg.go.dev/github.com/plenoai/pleno-dlp@v0.12.0/pkg/detectors/cloudflarer2)） |
| `R2_BUCKET` | 19 | — | `drug-brand-crossref` |
| `.env` 行结构 | 8 行、无重复键、无换行折断、无引号/空白残留 | — | 排除「粘贴时被换行截断」的读入问题：文件里就是 62 位 |

`SignatureDoesNotMatch` 的语义是「R2 认得这个 access key id，但用真实 secret 算出的签名和你给的对不上」——access key id 错会是 `InvalidAccessKeyId`，bucket/account 错会是 `NoSuchBucket` / DNS 错。
**结论：secret 被截断或贴错（少 2 位），只能由人重新取一次。**

## 3. 需要人做的事（1 件，3 步）

1. **Cloudflare Dashboard → R2 → Manage R2 API Tokens**：找到给这个 bucket 用的 token；若看不到 secret（secret 只在创建时显示一次），直接 **Create API token** 新建一个：
   - Permissions：**Object Read & Write**
   - Specify bucket：**`drug-brand-crossref`**（不要给全账号权限）
2. 复制 **Secret Access Key（64 位十六进制）**；`Access Key ID`（32 位）若无变化可沿用旧值。
3. 打开仓库根 `.env`，替换这一行（**不要加引号、不要留空格**），保存：

   ```
   R2_SECRET_ACCESS_KEY=<64 位十六进制>
   ```

   然后回一句「R2 secret 已更新」。我这边立刻按 §4 顺序跑，不需要你做别的。

> 如果你确认面板上的 secret 本来就是 62 位（不是复制丢字符），那就是该 token 已被轮换/删除——同样按上面「新建 token」处理即可。

## 4. 凭证一好，我这边按这个顺序跑（已备好）

| 步 | 命令 | 验收 |
|---|---|---|
| 1 | `deploy\sync_r2.ps1 -CheckOnly` | exit 0 或只剩「目标缺文件」；能列出 bucket（对象数/字节可读） |
| 2 | `deploy\sync_r2.ps1 -DryRun` | 打印将上传的对象数；**若发现桶里已有旧内容，先停下来报人，不覆盖** |
| 3 | `deploy\sync_r2.ps1` | 全量上传 121,450 文件 / 898,159,644 B；结束自动 `rclone check --size-only` |
| 4 | HTTP 验证（见 §5） | 200 + 页脚 v0.11.0 + 四语 + core.json gzip 区间 + 404 行为 |
| 5 | 写本报告「切后」一节 + 报 Lead | 域名已切 / 未切 + 卡点 |

同步策略：**直接全量同步到 bucket 根**（`rclone sync site/dist r2:bucket --checksum --transfers 32 --fast-list`），不做 `staging/` 预演——新域名当前无流量，阶段可见性可接受；不用 `publish.ps1 -WithR2`（该参数当前不存在，`publish.ps1` 参数表里没有）。

## 5. 切后必须验证的项（R2 与 gh-pages 行为差异已知风险）

| 检查 | 预期 / 风险 |
|---|---|
| `https://drugcrossref.com/` | 200 + 页脚 **v0.11.0**；R2 自定义域是否自动把 `/` 映射到 `index.html` 需实测 |
| `/zh/` `/es/` `/zh-hant/` | R2 **不保证**把 `/zh/` 映射到 `/zh/index.html`（静态托管常见缺口）；不生效就写「已知缺口 + 方案（Cloudflare Rules / Worker rewrite）」，不阻塞 v0.11.0 主线 |
| `/404.html` 与不存在路径 | R2 不会自动把 `/404.html` 当缺省 404；实测 `/nope` 返回什么，差距写进报告 |
| `index.html` Content-Type | 应为 `text/html; charset=utf-8`（rclone 按扩展名猜，可能少了 charset，需实测） |
| `data/idx/core.json` | `Content-Type: application/json` + gzip 后 2.5–12 MB（Cloudflare 边缘压缩是否生效要实测；R2 源站不压缩） |
| 静态资源 Cache-Control | R2 默认无长缓存头；如需 `immutable` 要另配规则（记缺口，不改本轮） |
| sitemap / robots | 200；sitemap 63,685 URL |

## 6. 成本（Free 额度核对，本轮未发生）

| 项 | 量 | Free 额度 | 结论 |
|---|---|---|---|
| 存储 | 898,159,644 B ≈ **856.6 MiB** | 10 GiB | 0 元（占 8.4%） |
| Class A（写） | 121,450 对象 × 1 次 ≈ **12.1 万** | 100 万/月 | 0 元（占 12%） |
| Class B（读） | 取决于访问量 | 1000 万/月 | 域名刚启用，0 元 |
| 出网 | Cloudflare 自定义域不计 R2 出网费 | — | 0 元 |

## 7. 回滚

- 本轮**没有切换**，无需回滚；`gh-pages` 一直是唯一线上。
- 以后切到 R2 后：`gh-pages` 原样保留 30 天（`e95552bd`=v0.10.3、`6946d8e42`=v0.11.0），
  出问题把 DNS/自定义域指回 `fuarnos.github.io/drug-brand-crossref/` 即可；
- R2 侧回滚：bucket 是对象存储没有版本历史，**重跑一次上一版 `site/dist` 的 sync** 即回退（`gh-pages` 有完整历史）。

## 8. 复现命令

```powershell
$py = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1 -CheckOnly
Get-Content .tmp\release-v0110-r2\r2-checkonly.log -Tail 6
# 形状检查（不打印值）
(Get-Content .env | Where-Object { $_ -match '^R2_SECRET_ACCESS_KEY=' }) -replace '^R2_SECRET_ACCESS_KEY=','' | ForEach-Object { $_.Trim().Length }
```

HTTP 现状（2026-11-10 11:39 实测）：`https://drugcrossref.com/`、`/nope`、`/index.html` 均 **404 / server: cloudflare**（CF-RAY `a587853…-LAX`），页面是 Cloudflare 通用 404，不是站点 404。
