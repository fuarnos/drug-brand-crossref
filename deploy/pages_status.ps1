# pages_status.ps1 — 查 GitHub Pages 的「服务模式 / 最近一次构建」状态（只读）。
#
# 背景：v0.9.6（gh-pages fbf67c5a）起 legacy 构建连续失败，API 只回
# "Page build failed."，没有任何细节。排查时第一件事就是把「设置 + 最近 6 次构建」
# 拉下来看清时间线，不要靠猜。
#
# 用法（在仓库根跑，token 从 .env 的 GITHUB_TOKEN 读，永不打印）：
#   & .\deploy\pages_status.ps1                     # 打一次快照
#   & .\deploy\pages_status.ps1 -Wait -MaxMinutes 15  # 轮询到终态（built/errored）或超时
#   & .\deploy\pages_status.ps1 -Wait -Quiet         # 只打变化行，适合放后台
#
# 退出码：0 = 最近一次构建 built（-Wait 时）；1 = errored / 超时；2 = 参数或网络问题。

[CmdletBinding()]
param(
    [switch]$Wait,
    [int]$MaxMinutes = 15,
    [int]$IntervalSeconds = 20,
    [int]$History = 6,
    [switch]$Quiet
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
    'User-Agent'           = 'drug-brand-crossref-pages-status/1.0'
}

function Get-Pages([string]$Path) {
    return Invoke-RestMethod -Uri "$Api/$Path" -Headers $headers -Method Get -TimeoutSec 60
}

function Format-Build($b) {
    if (-not $b) { return 'none' }
    $id = ($b.url -split '/')[-1]
    $err = ''
    if ($b.error -and $b.error.message) { $err = " error=$($b.error.message)" }
    return ("build {0} status={1} commit={2} created={3} updated={4} duration={5}ms{6}" -f `
            $id, $b.status, $b.commit.Substring(0, 8), $b.created_at, $b.updated_at, $b.duration, $err)
}

try {
    $site = Get-Pages 'pages'
} catch {
    Write-Output "无法读取 Pages 设置：$($_.Exception.Message)"
    if ($_.ErrorDetails.Message) { Write-Output $_.ErrorDetails.Message }
    exit 2
}

if (-not $Quiet) {
    Write-Output ("Pages: status={0} build_type={1} source={2}{3} https_enforced={4}" -f `
        $site.status, $site.build_type, $site.source.branch, $site.source.path, $site.https_enforced)
    Write-Output ("url: {0}" -f $site.html_url)
    try {
        # PS 5.1 的 Invoke-RestMethod 有时把 JSON 数组包成「单元素数组里再套数组」，
        # 不展平的话 foreach 只会拿到整块数组、每行打印 System.Object[]。
        $raw = Get-Pages "pages/builds?per_page=$History"
        $all = New-Object System.Collections.ArrayList
        foreach ($x in @($raw)) {
            if ($x -is [System.Array]) { foreach ($y in $x) { [void]$all.Add($y) } }
            else { [void]$all.Add($x) }
        }
        Write-Output "--- 最近 $($all.Count) 次构建 ---"
        foreach ($b in $all) { Write-Output ("  " + (Format-Build $b)) }
    } catch {
        Write-Output "读取构建历史失败：$($_.Exception.Message)"
    }
}

$latest = Get-Pages 'pages/builds/latest'
$lastLine = Format-Build $latest
if (-not $Quiet) { Write-Output "--- latest ---"; Write-Output ("  " + $lastLine) }

if (-not $Wait) {
    if ($latest.status -eq 'built') { exit 0 }
    if ($latest.status -eq 'errored') { exit 1 }
    exit 0
}

# 轮询到终态。legacy 构建正常 90–150 s 完成；超过 15 min 仍是 building 基本等于卡死。
$deadline = (Get-Date).AddMinutes($MaxMinutes)
$lastKey = ''
Write-Output ("[wait] 开始轮询（最多 {0} 分钟，每 {1} s）" -f $MaxMinutes, $IntervalSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds $IntervalSeconds
    try { $latest = Get-Pages 'pages/builds/latest' } catch { Write-Output "[wait] 查询失败：$($_.Exception.Message)"; continue }
    $key = "$($latest.url)|$($latest.status)"
    if ($key -ne $lastKey) {
        $lastKey = $key
        Write-Output ("[wait] {0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), (Format-Build $latest))
    }
    if ($latest.status -eq 'built') {
        Write-Output '[wait] 构建成功（built）'
        exit 0
    }
    if ($latest.status -eq 'errored') {
        Write-Output '[wait] 构建失败（errored）'
        exit 1
    }
}

Write-Output ("[wait] 超时：{0} 分钟后仍是 {1}（legacy 正常 90–150 s，超过 15 min 视为卡死）" -f $MaxMinutes, $latest.status)
exit 1
