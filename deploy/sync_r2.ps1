<#
.SYNOPSIS
    Sync site/dist to a Cloudflare R2 bucket (static hosting).

.DESCRIPTION
    Reads R2 credentials from .env at the repo root (R2_ACCOUNT_ID,
    R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET), writes a temporary
    rclone.conf under %TEMP%, runs rclone sync, then deletes the config.
    Credentials never touch the repo or the command line log.

    Intended as the R2 half of the publish pipeline (called by
    deploy\publish.ps1 -WithR2), but can be run alone.

.PARAMETER Dist
    Build directory. Default site\dist.

.PARAMETER DryRun
    List what would change; upload nothing.

.PARAMETER CheckOnly
    Skip the sync; only run rclone check (size-only) against the bucket.

.PARAMETER Transfers
    Concurrent transfers. Default 32.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1 -DryRun
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1 -CheckOnly

.NOTES
    Exit codes: 0 ok, 2 missing credentials / rclone / dist, 1 rclone failure.
    Rollback: the gh-pages copy stays live for 30 days (see DEPLOY.md).
#>
[CmdletBinding()]
param(
    [string]$Dist = '',
    [switch]$DryRun,
    [switch]$CheckOnly,
    [int]$Transfers = 32
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$Root = Split-Path $PSScriptRoot -Parent
if (-not $Dist) { $Dist = Join-Path $Root 'site\dist' }
elseif (-not [System.IO.Path]::IsPathRooted($Dist)) { $Dist = Join-Path $Root $Dist }

function Read-DotEnv([string]$Path) {
    $map = @{}
    if (-not (Test-Path $Path)) { return $map }
    foreach ($line in Get-Content $Path -Encoding UTF8) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('=')
        if ($i -lt 1) { continue }
        $k = $t.Substring(0, $i).Trim()
        $v = $t.Substring($i + 1).Trim().Trim('"')
        $map[$k] = $v
    }
    return $map
}

$dotenv = Read-DotEnv (Join-Path $Root '.env')
$need = @('R2_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET')
$missing = @($need | Where-Object { -not $dotenv[$_] })
if ($missing.Count) {
    Write-Host ("ERROR: .env is missing: {0}" -f ($missing -join ', '))
    Write-Host 'Add the R2_* lines to .env (see docs/托管迁移执行清单.md).'
    exit 2
}

$account = $dotenv['R2_ACCOUNT_ID']
$bucket = $dotenv['R2_BUCKET']

$rclone = Join-Path $Root 'tools\rclone.exe'
if (-not (Test-Path $rclone)) {
    Write-Host ("ERROR: rclone.exe not found at {0}" -f $rclone)
    Write-Host 'Download rclone into tools/ (gitignored); see docs/托管迁移执行清单.md.'
    exit 2
}
if (-not (Test-Path $Dist)) {
    Write-Host ("ERROR: dist not found: {0}" -f $Dist)
    exit 2
}

$conf = Join-Path $env:TEMP ("rclone-r2-{0}.conf" -f $PID)
try {
    $lines = @(
        '[r2]'
        'type = s3'
        'provider = Cloudflare'
        ('access_key_id = {0}' -f $dotenv['R2_ACCESS_KEY_ID'])
        ('secret_access_key = {0}' -f $dotenv['R2_SECRET_ACCESS_KEY'])
        ('endpoint = https://{0}.r2.cloudflarestorage.com' -f $account)
        'acl = private'
        'no_check_bucket = true'
    )
    Set-Content -Path $conf -Value $lines -Encoding ASCII

    $confArgs = @('--config', $conf, '--fast-list')

    if ($CheckOnly) {
        Write-Host ("check: {0} -> r2:{1} (size-only)" -f $Dist, $bucket)
        & $rclone check $Dist ("r2:{0}" -f $bucket) --size-only @confArgs
        if ($LASTEXITCODE -ne 0) { Write-Host 'ERROR: rclone check failed'; exit 1 }
        Write-Host 'check: OK (size-only)'
        exit 0
    }

    $syncArgs = @('sync', $Dist, ("r2:{0}" -f $bucket), '--checksum',
                  '--transfers', $Transfers, '--checkers', $Transfers) + $confArgs
    if ($DryRun) { $syncArgs += '--dry-run' }

    Write-Host ("sync: {0} -> r2:{1} (dry-run={2})" -f $Dist, $bucket, [bool]$DryRun)
    & $rclone @syncArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host ("ERROR: rclone exit {0}" -f $LASTEXITCODE)
        exit 1
    }

    if (-not $DryRun) {
        Write-Host 'upload done; verifying sizes'
        & $rclone check $Dist ("r2:{0}" -f $bucket) --size-only @confArgs
        if ($LASTEXITCODE -ne 0) { Write-Host 'ERROR: rclone check failed'; exit 1 }
    }
    Write-Host 'OK'
    exit 0
}
finally {
    if (Test-Path $conf) { Remove-Item $conf -Force -ErrorAction SilentlyContinue }
}
