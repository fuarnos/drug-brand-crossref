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
    Skip the sync; only run rclone check (size-only, one-way: every local file
    must exist remotely). Ignores the synthetic fr/ fallback object and any
    pre-sync extras that the next sync would delete.

.PARAMETER Transfers
    Concurrent transfers / checkers. Default 64.

    2026-11-13 v0.11.5 measurements (same 125,510 files, 0 differences, exit 0):
    32 -> 55m13s, 64 -> 21m15s. Runtime is roughly inversely proportional to
    concurrency: the average file is ~7.8 KB, so the bottleneck is R2
    round-trip latency, not bandwidth. Concurrency does NOT change the R2
    Class A write count: one full sync is still ~117k PUTs (dry-run basis),
    well under the 1M/month free tier (two publishes = ~234k). The cost is
    memory: rclone may buffer up to --buffer-size (default 16 MiB) per
    transfer, so 64 transfers is ~1 GiB worst case (actual files average
    7.8 KB, so far less in practice). Fall back to -Transfers 32 if R2
    returns 429/503 or the machine is memory-tight.

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
    [int]$Transfers = 64
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

# -- Python resolution for the /fr/ fallback (fixed 2026-11-13) ----------------
# The old `$pyExe = if ($env:PYTHON) { $env:PYTHON } else { 'python' }` resolved
# to C:\Users\asus\AppData\Local\Microsoft\WindowsApps\python.exe here - the
# Microsoft Store app alias, which exits 9009 and prints nothing. The /fr/
# fallback was silently skipped (WARN only), so v0.11.5's first publish left
# /fr/ at 404 and the Lead had to replay the PUT by hand.
# Now resolve explicitly in the AGENTS.md section 2 order, and probe every
# candidate's capability: fix_fr_root.py needs botocore for SigV4 signing, so
# "python starts" is not enough - this host's `py` launcher is Python 3.15
# without botocore and would still fail with exit 2.
$FrRuntimePython = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

function Test-FrPython([string]$Exe) {
    # Probe: must start AND import botocore (fix_fr_root.py's only third-party dep).
    $ErrorActionPreference = 'SilentlyContinue'   # function scope only; rest of script unaffected
    try {
        $null = & $Exe -c 'import botocore' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Resolve-FrPython([string[]]$RuntimeCandidates = @($FrRuntimePython)) {
    # Order: $env:PYTHON -> python (PATH) -> py (PATH launcher) -> runtime path
    # documented in AGENTS.md. Skip WindowsApps app aliases by path (never run
    # them, to avoid popping the Store); the log still records exit 9009.
    $candidates = @()
    if ($env:PYTHON) { $candidates += [pscustomobject]@{ Exe = $env:PYTHON; Via = 'PYTHON' } }
    foreach ($name in @('python', 'py')) {
        $cmd = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { $candidates += [pscustomobject]@{ Exe = $cmd.Source; Via = $name } }
    }
    foreach ($rt in $RuntimeCandidates) { $candidates += [pscustomobject]@{ Exe = $rt; Via = 'runtime' } }

    foreach ($c in $candidates) {
        $exe = $c.Exe
        if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
            # $env:PYTHON may be a bare command name (e.g. "python"); resolve once more.
            $resolved = Get-Command $exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $resolved) {
                Write-Host ("fr/: skip {0}={1} (not found)" -f $c.Via, $exe)
                continue
            }
            $exe = $resolved.Source
        }
        if ($exe -match '\\WindowsApps\\') {
            Write-Host ("fr/: skip {0}={1} (Microsoft Store app alias, exit 9009)" -f $c.Via, $exe)
            continue
        }
        if (Test-FrPython $exe) {
            Write-Host ("fr/: python = {0} (via {1}; botocore ok)" -f $exe, $c.Via)
            return [pscustomobject]@{ Exe = $exe; Via = $c.Via }
        }
        Write-Host ("fr/: skip {0}={1} (import botocore failed)" -f $c.Via, $exe)
    }
    return $null
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
        # --one-way: the bucket intentionally holds the synthetic `fr/` fallback object
        # (not in site/dist), and may hold pre-sync extras that the next sync deletes;
        # a strict two-way check would always report those as differences (2026-11-13:
        # without --one-way, -CheckOnly exited 1 with `1 differences / 1 files missing`
        # on a healthy bucket, purely because of fr/).
        Write-Host ("check: {0} -> r2:{1} (size-only, one-way)" -f $Dist, $bucket)
        & $rclone check $Dist ("r2:{0}" -f $bucket) --size-only --one-way @confArgs
        if ($LASTEXITCODE -ne 0) { Write-Host 'ERROR: rclone check failed'; exit 1 }
        Write-Host 'check: OK (size-only, one-way)'
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

        # TEMPORARY FIX (approved 2026-11-13): Cloudflare Transform Rules currently only cover
        # /, /zh/, /es/, /zh-hant/ - NOT /fr/ - so https://drugcrossref.com/fr/ 404s while
        # /fr/index.html is fine. We PUT fr/index.html as object key "fr/" to work around it.
        # That key is not part of site/dist, so every sync deletes it -> replay after each sync.
        # FINAL FIX: add the 5th Transform Rule (/fr/ -> /fr/index.html) in Cloudflare; then drop this.
        # Only fr/ is handled; a failure here only warns (upload success still exits 0),
        # but https://drugcrossref.com/fr/ 404s until it is fixed, and verify_live.py gates
        # every LANG_ROOT (incl. fr/) - so a release cannot pass silently with a broken /fr/.
        try {
            $frPy = Resolve-FrPython
            if ($frPy) {
                & $frPy.Exe (Join-Path $PSScriptRoot 'fix_fr_root.py') --dist $Dist
                if ($LASTEXITCODE -ne 0) {
                    Write-Host ("WARN: /fr/ fallback object NOT written (fix_fr_root.py exit {0}, python={1}); https://drugcrossref.com/fr/ will 404 until the 5th Transform Rule is added in Cloudflare." -f $LASTEXITCODE, $frPy.Exe)
                }
            } else {
                Write-Host 'WARN: /fr/ fallback NOT written (fix_fr_root.py exit 9009 = no usable python: tried $env:PYTHON, python, py, runtime path; all missing or lacking botocore); https://drugcrossref.com/fr/ will 404 until the 5th Transform Rule is added in Cloudflare.'
            }
        } catch {
            Write-Host ("WARN: /fr/ fallback not executed ({0}); https://drugcrossref.com/fr/ may 404 until the 5th Transform Rule is added in Cloudflare." -f $_.Exception.Message)
        }
    }
    Write-Host 'OK'
    exit 0
}
finally {
    if (Test-Path $conf) { Remove-Item $conf -Force -ErrorAction SilentlyContinue }
}
