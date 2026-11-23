<#
.SYNOPSIS
    REL6: append the content-hashed assets of the current site/dist to the keep-alive manifest
    data/legacy_assets.json.

.DESCRIPTION
    Why: every release that changes CSS/JS mints a new assets/style.<sha256[:10]>.css and
    assets/boot.<sha256[:10]>.js (site/build.py). `rclone sync` (deploy/sync_r2.ps1) deletes the
    previous release's hash-named files, so a page still cached in a browser 404s on them
    (v1.0.1 lost boot.882e52f15e.js exactly that way). sync_r2.ps1 keeps the manifest entries
    alive with exact `--exclude assets/<name>` args; this script is the only writer of the
    manifest (sync_r2.ps1 only reads it).

    ORDER MATTERS: run this BEFORE site/build.py. Until the build rewrites it, site/dist holds
    the PREVIOUS release - the only moment those outgoing hash names are still on disk.
    Runbook: collect_legacy_assets.ps1 -> site\build.py -> sync_r2.ps1.

    Rules:
      * a collected name must match ^(style|boot)\.[0-9a-f]{10}\.(css|js)$ (the stable names
        assets/style.css / assets/boot.js are skipped); wildcards are never written;
      * new entry: expires = collect date (Beijing) + -RetentionDays (default 30);
      * an already tracked name is left untouched (dedupe; idempotent - a second run on the same
        dist writes nothing, so `git diff` stays clean);
      * a tracked name that already expired but is shipped again is re-activated (loudly);
      * -PruneExpired additionally drops entries whose `expires` day has passed (off by default
        so the keep-alive history stays reviewable; sync_r2.ps1 ignores them anyway).

    The manifest also keeps `generated_at` / `notes` / `name_pattern` from the existing file, so
    a rewrite only changes the entries and `updated_at`.

.PARAMETER Dist
    Build directory to read. Default site\dist.

.PARAMETER ManifestPath
    Manifest to update. Default data\legacy_assets.json (relative paths resolve from the repo
    root).

.PARAMETER RetentionDays
    Keep-alive window in days for newly collected names. Default 30.

.PARAMETER DryRun
    Print what would change; write nothing (runbooks and the REL6 self-test).

.PARAMETER PruneExpired
    Also drop entries whose `expires` day has passed before writing.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\collect_legacy_assets.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\collect_legacy_assets.ps1 -DryRun
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\collect_legacy_assets.ps1 -Dist .tmp\rel6-dist -ManifestPath .tmp\rel6-manifest.json

.NOTES
    Exit codes: 0 ok (also when site/dist has no assets\ yet), 2 dist / manifest problem (an
    unparsable manifest is never overwritten), 1 write failure.
    Dates use Beijing time (the release window is Beijing 00:30-08:30); `expires` is inclusive:
    an entry stays protected through that date and is ignored afterwards.
#>
[CmdletBinding()]
param(
    [string]$Dist = '',
    [string]$ManifestPath = '',
    [int]$RetentionDays = 30,
    [switch]$DryRun,
    [switch]$PruneExpired
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$Root = Split-Path $PSScriptRoot -Parent
if (-not $Dist) { $Dist = Join-Path $Root 'site\dist' }
elseif (-not [System.IO.Path]::IsPathRooted($Dist)) { $Dist = Join-Path $Root $Dist }
if (-not $ManifestPath) { $ManifestPath = Join-Path $Root 'data\legacy_assets.json' }
elseif (-not [System.IO.Path]::IsPathRooted($ManifestPath)) { $ManifestPath = Join-Path $Root $ManifestPath }

# Keep this pattern in sync with sync_r2.ps1 ($LegacyAssetNamePattern) and site/build.py
# (assets/style.<sha256[:10]>.css / assets/boot.<sha256[:10]>.js).
$NamePattern = '^(style|boot)\.[0-9a-f]{10}\.(css|js)$'
$DefaultNotes = 'REL6 (2026-11-24) keep-alive manifest for content-hashed assets under assets/. Exact file names only, no wildcards. expires is inclusive: an entry becomes an exact rclone --exclude through that date and is ignored afterwards. Read by deploy/sync_r2.ps1; appended by deploy/collect_legacy_assets.ps1, which MUST run before site/build.py because the build overwrites site/dist. The two rel2-b-hardcoded rows are the pre-REL6 hand-written pair (retire 2026-12-20) and stay hard-coded in sync_r2.ps1 as well until that date.'

function Get-ReleaseToday {
    # Repo docs / reports use Beijing dates (AGENTS.md section 12) while the release host may be
    # UTC-8, so an overnight Beijing release would otherwise evaluate expiry one day early.
    try {
        $bj = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), 'China Standard Time')
        if ($bj) { return $bj.Date }
    } catch { }
    return (Get-Date).Date
}

$today = Get-ReleaseToday
$todayStr = $today.ToString('yyyy-MM-dd')
Write-Host ("collect: dist = {0}" -f $Dist)
Write-Host ("collect: manifest = {0}" -f $ManifestPath)
Write-Host ("collect: today (Beijing) = {0}; retention = {1} day(s) -> new entries expire {2}" -f $todayStr, $RetentionDays, $today.AddDays($RetentionDays).ToString('yyyy-MM-dd'))

# -- read the existing manifest (never overwrite something we cannot parse) --
$rows = @()
$dropped = @()
$genAt = $todayStr
$notes = $DefaultNotes
$namePattern = $NamePattern
if (Test-Path -LiteralPath $ManifestPath) {
    try {
        $doc = (Get-Content -LiteralPath $ManifestPath -Encoding UTF8 -Raw) | ConvertFrom-Json
    } catch {
        Write-Host ("ERROR: manifest is not valid JSON, refusing to overwrite it: {0}" -f $_.Exception.Message)
        exit 2
    }
    if ($doc.generated_at) { $genAt = [string]$doc.generated_at }
    if ($doc.notes) { $notes = [string]$doc.notes }
    if ($doc.name_pattern) { $namePattern = [string]$doc.name_pattern }
    foreach ($e in @($doc.entries)) {
        if ($null -eq $e) { continue }
        $n = [string]$e.name
        $exp = [string]$e.expires
        if (-not ($n -match $NamePattern) -or $n -match '[\*\?\[]') {
            Write-Host ("WARN: dropping invalid manifest entry '{0}' on rewrite (not an exact, wildcard-free hashed asset name)" -f $n)
            $dropped += $n
            continue
        }
        if ($exp -notmatch '^\d{4}-\d{2}-\d{2}$') {
            Write-Host ("WARN: dropping manifest entry '{0}' on rewrite (bad expires '{1}')" -f $n, $exp)
            $dropped += $n
            continue
        }
        $added = $todayStr
        if ($e.added) { $added = [string]$e.added }
        $source = 'manifest'
        if ($e.source) { $source = [string]$e.source }
        $rows += [ordered]@{ name = $n; added = $added; expires = $exp; source = $source }
    }
}
Write-Host ("collect: existing manifest = {0} entr(ies)" -f $rows.Count)
$index = @{}
for ($i = 0; $i -lt $rows.Count; $i++) { $index[[string]$rows[$i]['name']] = $i }

# -- scan the build directory for hash-named assets --------------------------
$assetsDir = Join-Path $Dist 'assets'
$found = @()
if (-not (Test-Path -LiteralPath $assetsDir)) {
    Write-Host ("WARN: no assets\ directory under {0} - nothing to collect (first build on this machine?); manifest untouched" -f $Dist)
} else {
    $files = @(Get-ChildItem -LiteralPath $assetsDir -File -Force)
    $found = @($files | Where-Object { $_.Name -match $NamePattern } | ForEach-Object { $_.Name } | Sort-Object -Unique)
    foreach ($f in $files) {
        if ($f.Name -notmatch $NamePattern -and $f.Name -match '^(style|boot)\.[0-9A-Za-z_-]+\.[A-Za-z]+$') {
            Write-Host ("WARN: assets/{0} looks hash-named but does not match {1}; not collected" -f $f.Name, $NamePattern)
        }
    }
}
$foundText = '(none)'
if ($found.Count) { $foundText = ($found -join ', ') }
Write-Host ("collect: found {0} hashed asset(s): {1}" -f $found.Count, $foundText)

# -- merge (dedupe by name; expired names that are shipped again get re-activated) --
$added = @()
$reactivated = @()
$alreadyTracked = 0
foreach ($name in $found) {
    if ($index.ContainsKey($name)) {
        $i = $index[$name]
        if ([string]$rows[$i]['expires'] -lt $todayStr) {
            $rows[$i]['expires'] = $today.AddDays($RetentionDays).ToString('yyyy-MM-dd')
            $rows[$i]['source'] = 'recollected'
            $reactivated += $name
            Write-Host ("collect:   ~ assets/{0}  re-activated, expires {1}" -f $name, $rows[$i]['expires'])
        } else {
            $alreadyTracked++
        }
    } else {
        $rows += [ordered]@{
            name    = $name
            added   = $todayStr
            expires = $today.AddDays($RetentionDays).ToString('yyyy-MM-dd')
            source  = 'collect'
        }
        $index[$name] = $rows.Count - 1
        $added += $name
        Write-Host ("collect:   + assets/{0}  expires {1}" -f $name, $rows[$index[$name]]['expires'])
    }
}

$pruned = @()
if ($PruneExpired) {
    $kept = @()
    foreach ($r in $rows) {
        if ([string]$r['expires'] -lt $todayStr) {
            $pruned += [string]$r['name']
            Write-Host ("collect:   - assets/{0}  pruned (expired {1})" -f [string]$r['name'], [string]$r['expires'])
        } else {
            $kept += $r
        }
    }
    $rows = @($kept)
}

$activeCount = @($rows | Where-Object { [string]$_['expires'] -ge $todayStr }).Count
$expiredCount = $rows.Count - $activeCount
Write-Host ("collect: added {0}, re-activated {1}, pruned {2}, dropped-invalid {3}, already tracked {4}" -f $added.Count, $reactivated.Count, $pruned.Count, $dropped.Count, $alreadyTracked)
Write-Host ("collect: manifest would hold {0} entr(ies) = {1} active (kept alive by sync_r2.ps1) + {2} expired (ignored)" -f $rows.Count, $activeCount, $expiredCount)

$changeCount = $added.Count + $reactivated.Count + $pruned.Count + $dropped.Count
$changed = ($changeCount -gt 0)
if (-not $changed) {
    Write-Host ("collect: no change ({0} entr(ies) already cover this dist); manifest not rewritten (idempotent)" -f $rows.Count)
} elseif ($DryRun) {
    Write-Host ("collect: DRY RUN - {0} change(s) not written" -f $changeCount)
} else {
    $out = [ordered]@{
        schema         = 1
        generated_at   = $genAt
        updated_at     = $todayStr
        retention_days = $RetentionDays
        name_pattern   = $namePattern
        notes          = $notes
        entries        = @($rows)
    }
    # UTF-8 without BOM + LF: readable by ConvertFrom-Json here and by python json.loads, and it
    # keeps the repository line endings uniform (AGENTS.md section 5).
    $json = ($out | ConvertTo-Json -Depth 6) -replace "`r`n", "`n"
    if (-not $json.EndsWith("`n")) { $json += "`n" }
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $dir = Split-Path -Parent $ManifestPath
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    try {
        [System.IO.File]::WriteAllText($ManifestPath, $json, $utf8)
    } catch {
        Write-Host ("ERROR: writing manifest failed: {0}" -f $_.Exception.Message)
        exit 1
    }
    Write-Host ("collect: wrote {0} ({1} entr(ies))" -f $ManifestPath, $rows.Count)
}
Write-Host 'next: run site/build.py, then deploy\sync_r2.ps1 (collect must stay BEFORE the build)'
exit 0
