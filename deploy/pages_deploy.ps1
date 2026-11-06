# pages_deploy.ps1 — GitHub Pages 部署侧的操作工具（状态 / 兜底 dispatch / 切源 / 回滚）。
#
# 这里只做「部署侧」的事：不改 gh-pages 内容、不重建站点、不碰 site/dist。
# 正常发版仍然走 deploy/publish.ps1（推送 gh-pages + legacy 构建）；
# 只有在 legacy 构建连续失败时才用本脚本的 -Dispatch / -SwitchToWorkflow。
#
# 用法（仓库根，token 从 .env 的 GITHUB_TOKEN 读，永不打印）：
#   & .\deploy\pages_deploy.ps1 -Status              # 只读：设置 + 最近构建（默认动作）
#   & .\deploy\pages_deploy.ps1 -RetryBuild          # POST /pages/builds（legacy 重试一次）
#   & .\deploy\pages_deploy.ps1 -SwitchToWorkflow    # 切 Source=GitHub Actions（会中断 legacy 发布！）
#   & .\deploy\pages_deploy.ps1 -Dispatch            # 触发 pages-fallback workflow（需已切源）
#   & .\deploy\pages_deploy.ps1 -RollbackToBranch    # 回滚：Source 切回 gh-pages 分支
#   任一动作都可加 -DryRun 只打印请求、不真正发出。
#
# 注意：-SwitchToWorkflow 之后，在 workflows/pages-fallback.yml 成功部署前，
# 线上会 404（branch 发布被停用）。务必按「先提交 workflow → 再切源 → 立刻 dispatch」
# 的顺序做；要回退见 -RollbackToBranch。
#
# 已知限制（2026-11-06 实测）：仓库 .env 里的 GITHUB_TOKEN 是**不含 pages:write 的
# fine-grained PAT**，PUT /repos/{owner}/{repo}/pages 返回 403
# "Resource not accessible by personal access token"。也就是说：
#   - -RetryBuild / -Dispatch / -Status 可用；
#   - -SwitchToWorkflow / -RollbackToBranch 需要换成带 Pages:write 的 token，
#     或者由人在 Settings → Pages → Source 里点。
#   （重试 POST /pages/builds 只要求 repo 的 push 权限，本次事故就是靠它恢复的。）

[CmdletBinding()]
param(
    [switch]$Status,
    [switch]$RetryBuild,
    [switch]$SwitchToWorkflow,
    [switch]$Dispatch,
    [switch]$RollbackToBranch,
    [string]$WorkflowFile = 'pages-fallback.yml',
    [string]$Ref = 'main',
    [switch]$DryRun,
    [int]$History = 8
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Repo = 'fuarnos/drug-brand-crossref'
$Api = "https://api.github.com/repos/$Repo"

function Get-Token {
    $envFile = Join-Path $Root '.env'
    if (-not (Test-Path $envFile)) { throw "缺少 $envFile（需要 GITHUB_TOKEN）" }
    $line = Get-Content $envFile | Where-Object { $_ -match '^GITHUB_TOKEN=' } | Select-Object -First 1
    if (-not $line) { throw "$envFile 里没有 GITHUB_TOKEN" }
    return (($line -replace '^GITHUB_TOKEN=\s*', '').Trim().Trim('"').Trim("'"))
}

$headers = @{
    Authorization          = "Bearer $(Get-Token)"
    Accept                 = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
    'User-Agent'           = 'drug-brand-crossref-pages-deploy/1.0'
}

function Format-Build($b) {
    if (-not $b) { return 'none' }
    $id = ($b.url -split '/')[-1]
    $err = ''
    if ($b.error -and $b.error.message) { $err = " error=$($b.error.message)" }
    return ("build {0} status={1} commit={2} created={3} updated={4} duration={5}ms{6}" -f `
            $id, $b.status, $b.commit.Substring(0, 8), $b.created_at, $b.updated_at, $b.duration, $err)
}

function Show-Status {
    $site = Invoke-RestMethod -Uri "$Api/pages" -Headers $headers -TimeoutSec 60
    Write-Output ("Pages: status={0} build_type={1} source={2}{3} https_enforced={4}" -f `
        $site.status, $site.build_type, ($(if ($site.source) { $site.source.branch } else { '(workflow)' })),
        ($(if ($site.source) { $site.source.path } else { '' })), $site.https_enforced)
    Write-Output ("url: {0}" -f $site.html_url)
    $raw = Invoke-RestMethod -Uri ("$Api/pages/builds?per_page=$History") -Headers $headers -TimeoutSec 60
    $all = New-Object System.Collections.ArrayList
    foreach ($x in @($raw)) {
        if ($x -is [System.Array]) { foreach ($y in $x) { [void]$all.Add($y) } } else { [void]$all.Add($x) }
    }
    Write-Output "--- 最近 $($all.Count) 次构建 ---"
    foreach ($b in $all) { Write-Output ("  " + (Format-Build $b)) }
    $latest = Invoke-RestMethod -Uri "$Api/pages/builds/latest" -Headers $headers -TimeoutSec 60
    Write-Output ("--- latest: " + (Format-Build $latest))
}

function Get-WorkflowId {
    $wf = Invoke-RestMethod -Uri "$Api/actions/workflows" -Headers $headers -TimeoutSec 60
    foreach ($w in $wf.workflows) {
        if ($w.path -match [regex]::Escape($WorkflowFile)) { return $w.id }
    }
    return $null
}

# ── 动作 ────────────────────────────────────────────────────────────────
if (-not ($Status -or $RetryBuild -or $SwitchToWorkflow -or $Dispatch -or $RollbackToBranch)) { $Status = $true }

if ($Status) {
    Show-Status
}

if ($RetryBuild) {
    $body = '{}'
    if ($DryRun) {
        Write-Output "[dry-run] POST $Api/pages/builds $body"
    } else {
        $r = Invoke-RestMethod -Uri "$Api/pages/builds" -Headers $headers -Method Post -Body $body `
                -ContentType 'application/json' -TimeoutSec 90
        Write-Output ("POST /pages/builds -> status={0}（legacy 构建正常工作 90–150 s，超过 15 min 视为卡死）" -f $r.status)
    }
}

if ($SwitchToWorkflow) {
    # 切到 Actions 发布：branch 发布立即停止，直到 pages-fallback 成功部署一次才会重新有站点！
    $body = '{"build_type":"workflow"}'
    if ($DryRun) {
        Write-Output "[dry-run] PUT $Api/pages $body"
    } else {
        Write-Output '警告：切源后线上将停止服务 branch 构建，直到 workflow 部署成功；中途回滚用 -RollbackToBranch'
        $r = Invoke-RestMethod -Uri "$Api/pages" -Headers $headers -Method Put -Body $body `
                -ContentType 'application/json' -TimeoutSec 90
        Write-Output ("PUT /pages -> build_type={0}" -f $r.build_type)
    }
}

if ($Dispatch) {
    $wfId = Get-WorkflowId
    $body = ('{{"ref":"{0}"}}' -f $Ref)
    if (-not $wfId) {
        if ($DryRun) {
            Write-Output "[dry-run] 远端还没有 $WorkflowFile（未提交到 $Ref 时 dispatch 不可用）"
        } else {
            throw "找不到 $WorkflowFile（是否还没提交到 main？）"
        }
    } elseif ($DryRun) {
        Write-Output "[dry-run] POST $Api/actions/workflows/$wfId/dispatches $body"
    } else {
        Invoke-RestMethod -Uri "$Api/actions/workflows/$wfId/dispatches" -Headers $headers -Method Post `
            -Body $body -ContentType 'application/json' -TimeoutSec 90 | Out-Null
        Write-Output "已触发 workflow $WorkflowFile（ref=$Ref），用 deploy/pages_status.ps1 看 Result，跑完再 verify_live"
    }
}

if ($RollbackToBranch) {
    # 回滚：Source 切回 gh-pages 分支，线上立刻回到上一个成功构建的 legacy 版本（如 v0.9.5）。
    $body = '{"build_type":"legacy","source":{"branch":"gh-pages","path":"/"}}'
    if ($DryRun) {
        Write-Output "[dry-run] PUT $Api/pages $body"
    } else {
        $r = Invoke-RestMethod -Uri "$Api/pages" -Headers $headers -Method Put -Body $body `
                -ContentType 'application/json' -TimeoutSec 90
        Write-Output ("PUT /pages -> build_type={0} source={1}{2}" -f $r.build_type, $r.source.branch, $r.source.path)
        Write-Output '回滚后 legacy 会重建一次；用 deploy/pages_status.ps1 -Wait 等 built，再 verify_live 验收'
    }
}
