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

    REL2 (2026-11-20) incremental-release support:
      * The main `rclone sync` keeps the pre-v1.0.0 content-hashed assets alive via
        two EXACT `--exclude`s (assets/style.885ce0a604.css,
        assets/boot.510d5a90dd.js, no wildcards) because pages cached before
        v1.0.0 still reference them; retire after 2026-12-20. The same excludes go
        to both `rclone check` runs: the post-sync check is two-way, so once
        site/dist stops shipping those files they would be "remote only" and fail
        the release with 2 differences.
      * After a successful sync, assets/ is copied once more with
        --ignore-times --header-upload "Cache-Control: public, max-age=300"
        (~17 extra Class A PUTs). The main sync only transfers changed files, so
        unchanged stable-name assets (assets/style.css / assets/boot.js) would
        never receive a Cache-Control header; 5 minutes caps the stale-UI window
        after a release without making HTML cacheable.

    REL3 (2026-11-21) R2 Class A budget guard + PUT ledger:
      * Before any upload the script reads data/r2_put_ledger.jsonl and sums the current
        month's real `files` values. Month-to-date >= 900,000 -> STOP with exit 3
        (report to Lead/human; this hard stop has no override).
      * A planning `rclone sync --dry-run` runs before the real upload, so the single-
        release gate is evaluated BEFORE spending Class A ops: planned > 50,000 needs an
        explicit -ApproveLarge (Lead approval); a projected month total >= 900,000 also
        needs -ApproveLarge; and projected >= 1,000,000 needs the USER's approval first
        (record it in the release report). -DryRun evaluates the same gates and exits 3
        instead of uploading (and never writes the ledger).
      * After a successful REAL sync the script appends one JSON line to the ledger:
        {"date":"YYYY-MM-DD","version":"vX.Y.Z","files":N,"seconds":S,"mode":"real"}.
        N is the last `Transferred: N / N, 100%` line = main-sync files = Class A PUTs
        (the assets pass deliberately prints no NOTICE stats). Budget numbers per publish
        additionally count +22: 17 assets PUTs + 5 language-root fallback PUTs.
        The v1.0.0 publish is NOT backfilled (task-4: no history backfill) - reconcile that cycle
        against the Cloudflare bill by hand.
      * Budget reference (AGENTS.md section 6): free 1M Class A/month, $4.50 per million
        above it, Cloudflare rounds UP to the next million; >1M needs user approval.

    REL6 (2026-11-24) data-driven keep-alive of content-hashed assets:
      * Every release that changes CSS/JS mints new assets/style.<sha256[:10]>.css and
        assets/boot.<sha256[:10]>.js names (site/build.py), and `rclone sync` deletes the
        previous version's hash-named files - so a browser still holding the old HTML 404s on
        them (v1.0.1 lost boot.882e52f15e.js exactly this way). REL2-B covered that with two
        hand-written exact excludes; REL6 replaces the hand-maintained list with
        data/legacy_assets.json, so every release no longer needs a manual edit.
      * deploy\collect_legacy_assets.ps1 appends the hashed names found in the CURRENT
        site/dist/assets (= the previous release) with expires = collect date + 30 days.
        Run it BEFORE site/build.py: the build overwrites site/dist, so afterwards those
        previous names are gone from disk.
      * This script reads the manifest, keeps the unexpired entries, and turns each one into an
        EXACT `--exclude assets/<name>` (regex-validated: style|boot + 10 hex + css|js). A
        wildcard entry is a hard error (exit 2), so the exclude set can never grow unbounded
        and a typo cannot silently protect the whole bucket. Expired entries are ignored
        automatically and printed as such.
      * The REL2-B pair stays hard-coded until 2026-12-20 and the manifest row wins on a name
        collision, so the transition has no gap; both lists feed the same exclude array.
      * Runbook order: collect -> build -> sync. The keep list (active / expired-ignored /
        invalid-ignored) is printed before any upload in BOTH -DryRun and real runs; -DryRun
        still writes nothing (no uploads, no ledger row).

.PARAMETER Dist
    Build directory. Default site\dist.

.PARAMETER DryRun
    List what would change; upload nothing.

.PARAMETER CheckOnly
    Skip the sync; only run rclone check (size-only, one-way: every local file
    must exist remotely). Ignores the synthetic language-root fallback objects
    (fr/, ko/) and any pre-sync extras that the next sync would delete.

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

.PARAMETER ApproveLarge
    Allow a release whose planned file count is > 50,000, or whose projected month total
    is >= 900,000 PUT. Requires Lead approval; projected >= 1,000,000 additionally needs
    the user's approval (write it into the release report). The month-to-date >= 900,000
    hard stop is NOT overridable.

.PARAMETER LedgerPath
    PUT ledger JSONL path. Default data\r2_put_ledger.jsonl (relative paths resolve from
    the repo root). Override only for tests / ops (e.g. a simulated ledger).

.PARAMETER ManifestPath
    REL6 keep-alive manifest. Default data\legacy_assets.json (relative paths resolve from the
    repo root). Read-only here - entries are appended by deploy\collect_legacy_assets.ps1.
    Each entry is an exact asset file name (style.<10 hex>.css / boot.<10 hex>.js), protected
    through its `expires` date inclusive, then ignored. Override only for tests / ops.

.PARAMETER ShowAssetExcludes
    Print the resolved keep list (active / expired-ignored / invalid-ignored) plus the exact
    `--exclude` arguments, then exit 0 before any credential or rclone work. For the release
    runbook and the REL6 self-test.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1 -DryRun
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1 -CheckOnly
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1 -LedgerPath .tmp\ledger.jsonl -DryRun
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\sync_r2.ps1 -ShowAssetExcludes

.NOTES
    Exit codes: 0 ok, 2 missing credentials / rclone / dist (or a wildcard / malformed keep
    list), 1 rclone failure, 3 budget / approval gate refused (month-to-date >= 900k,
    planned > 50k without -ApproveLarge, or projected month total >= 900k without
    -ApproveLarge). -ShowAssetExcludes exits 0 without touching credentials or rclone.
    Rollback: the gh-pages copy stays live for 30 days (see DEPLOY.md).

    Logs (Q8, 2026-11-18): the rclone stats block is now printed at NOTICE every 60s and once
    more at the end, so a captured release log carries the Class A write count and duration:
        Transferred:           117445 / 117445, 100%   <- files written = Class A PUTs
        Elapsed time:      21m15.0s                    <- sync duration
    Parse the LAST `Transferred: N / N, 100%` line. If nothing needed writing, rclone prints
    only `Transferred: 0 B / 0 B` (no N/N line) -> treat as 0 PUT. Logging flags only; the
    files selected, checksums and transfer parameters are unchanged.
    REL2-B (2026-11-20): the separate assets/ Cache-Control copy runs with
    --stats-log-level INFO and no -v, so it prints NO stats block - the last
    `Transferred:` line above stays the MAIN sync's, which is what the REL3 ledger parses.
    PUT budget per publish = that N + ~17 assets (the assets line `assets: re-uploading N`
    reports the second pass).
#>
[CmdletBinding()]
param(
    [string]$Dist = '',
    [switch]$DryRun,
    [switch]$CheckOnly,
    [int]$Transfers = 64,
    [switch]$ApproveLarge,
    [string]$LedgerPath = '',
    [string]$ManifestPath = '',
    [switch]$ShowAssetExcludes
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

# -- Python resolution for the language-root fallbacks (fixed 2026-11-13) -----
# The old `$pyExe = if ($env:PYTHON) { $env:PYTHON } else { 'python' }` resolved
# to C:\Users\asus\AppData\Local\Microsoft\WindowsApps\python.exe here - the
# Microsoft Store app alias, which exits 9009 and prints nothing. The /fr/
# fallback was silently skipped (WARN only), so v0.11.5's first publish left
# /fr/ at 404 and the Lead had to replay the PUT by hand.
# Now resolve explicitly in the AGENTS.md section 2 order, and probe every
# candidate's capability: fix_fr_root.py needs botocore for SigV4 signing, so
# "python starts" is not enough - this host's `py` launcher is Python 3.15
# without botocore and would still fail with exit 2.
$FallbackRuntimePython = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
# Languages whose landing page needs a synthetic object-key fallback: Cloudflare
# Transform Rules cover /, /zh/, /es/, /zh-hant/ only (no /fr/, no /ko/), so the
# page is served from R2 object key "<lang>/". Keep this list in sync with
# deploy/fix_fr_root.py LANG_ROOTS, deploy/verify_live.py LANG_ROOTS and
# data/languages.json ("新增 UI 语言时三处一起改").
$FallbackLangs = @('fr', 'ko', 'ja', 'cs', 'lv')

function Test-FallbackPython([string]$Exe) {
    # Probe: must start AND import botocore (fix_fr_root.py's only third-party dep).
    $ErrorActionPreference = 'SilentlyContinue'   # function scope only; rest of script unaffected
    try {
        $null = & $Exe -c 'import botocore' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Resolve-FallbackPython([string[]]$RuntimeCandidates = @($FallbackRuntimePython)) {
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
                Write-Host ("lang-root/: skip {0}={1} (not found)" -f $c.Via, $exe)
                continue
            }
            $exe = $resolved.Source
        }
        if ($exe -match '\\WindowsApps\\') {
            Write-Host ("lang-root/: skip {0}={1} (Microsoft Store app alias, exit 9009)" -f $c.Via, $exe)
            continue
        }
        if (Test-FallbackPython $exe) {
            Write-Host ("lang-root/: python = {0} (via {1}; botocore ok)" -f $exe, $c.Via)
            return [pscustomobject]@{ Exe = $exe; Via = $c.Via }
        }
        Write-Host ("lang-root/: skip {0}={1} (import botocore failed)" -f $c.Via, $exe)
    }
    return $null
}

function Get-ChangelogVersion {
    # Version source of truth = first CHANGELOG section (AGENTS.md section 6); unknown on failure.
    $p = Join-Path $Root 'CHANGELOG.md'
    if (Test-Path -LiteralPath $p) {
        foreach ($line in Get-Content -LiteralPath $p -Encoding UTF8) {
            if ($line -match '^##\s+(v\d+\.\d+\.\d+)') { return $Matches[1] }
        }
    }
    return 'unknown'
}

function Get-TransferredCount([string]$LogPath) {
    # Parse the LAST `Transferred: N / N, 100%` line (= files written this run = Class A PUTs).
    # 0 uploads prints only `Transferred: 0 B / 0 B` (no N/N line) -> 0.
    if (-not (Test-Path -LiteralPath $LogPath)) { return 0 }
    $hit = Select-String -LiteralPath $LogPath -Pattern 'Transferred:\s+(\d+)\s*/\s*(\d+),\s*100%' |
        Select-Object -Last 1
    if (-not $hit) { return 0 }
    return [int]$hit.Matches[0].Groups[1].Value
}

function Get-ElapsedSeconds([string]$LogPath) {
    # Parse rclone's own `Elapsed time: 18m50.9s` / `59.9s`; 0 on failure (caller falls back).
    if (-not (Test-Path -LiteralPath $LogPath)) { return 0 }
    $hit = Select-String -LiteralPath $LogPath -Pattern 'Elapsed time:\s+(?:(\d+)m)?([\d.]+)s' |
        Select-Object -Last 1
    if (-not $hit) { return 0 }
    $m = $hit.Matches[0]
    $sec = [double]$m.Groups[2].Value
    if ($m.Groups[1].Success) { $sec += 60.0 * [int]$m.Groups[1].Value }
    return $sec
}

function Write-RcloneSummary([string]$LogPath, [string]$Label) {
    # rclone runs with --log-file (so its NOTICE stats never reach PowerShell's error stream,
    # which would terminate the script under $ErrorActionPreference='Stop'). Echo the tail of
    # the stats block to the console so the caller's release log keeps the numbers.
    if (-not (Test-Path -LiteralPath $LogPath)) { return }
    $hits = Select-String -LiteralPath $LogPath -Encoding UTF8 -Pattern 'Transferred:|Deleted:|Elapsed time:' |
        Select-Object -Last 6
    foreach ($hit in $hits) { Write-Host ("{0}: {1}" -f $Label, $hit.Line.Trim()) }
}

function Show-RcloneTail([string]$LogPath, [string]$Label) {
    if (-not (Test-Path -LiteralPath $LogPath)) { return }
    Get-Content -LiteralPath $LogPath -Encoding UTF8 -Tail 20 |
        ForEach-Object { Write-Host ("{0}-log: {1}" -f $Label, $_) }
}

function Get-R2LedgerMonthTotal([string]$Path) {
    # Ledger month-to-date (local time) sum of real sync PUTs. Row format: see .DESCRIPTION.
    # Skip mode=dryrun and unparsable rows; legacy rows without mode count as real.
    $month = Get-Date -Format 'yyyy-MM'
    $sum = 0
    $rows = 0
    $bad = 0
    if (Test-Path -LiteralPath $Path) {
        foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
            if (-not $line.Trim()) { continue }
            try { $row = $line | ConvertFrom-Json } catch { $bad++; continue }
            if ($row.mode -eq 'dryrun') { continue }
            if (-not ($row.date -like "$month*")) { continue }
            if ($null -ne $row.files) {
                $sum += [int]$row.files
                $rows++
            }
        }
    }
    return [pscustomobject]@{ Month = $month; Total = $sum; Rows = $rows; Bad = $bad }
}

function Add-R2LedgerRow([string]$Path, [string]$Version, [int]$Files, [double]$Seconds) {
    # Append one JSONL line. UTF-8 without BOM + LF (a BOM breaks the first json.loads).
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    $row = [ordered]@{
        date    = (Get-Date -Format 'yyyy-MM-dd')
        version = $Version
        files   = $Files
        seconds = [math]::Round($Seconds, 1)
        mode    = 'real'
    }
    $json = ($row | ConvertTo-Json -Compress)
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::AppendAllText($Path, $json + "`n", $utf8)
}

# -- REL3 (2026-11-21): budget guard / PUT ledger helpers --
# (helper functions used by the budget guard below)

# -- REL6 (2026-11-24): data-driven keep-alive of content-hashed assets --------
# Contract: data\legacy_assets.json holds exact hashed asset file names (style.<10 hex>.css /
# boot.<10 hex>.js) with an inclusive `expires` date. Entries are appended by
# deploy\collect_legacy_assets.ps1 from the PREVIOUS site/dist/assets (run before
# site/build.py), and consumed here as exact `--exclude assets/<name>` arguments.
# Hard rules: no wildcards (a wildcard entry aborts with exit 2), expired entries are ignored
# automatically, and the REL2-B hand-written pair stays hard-coded until 2026-12-20 so the
# transition has no gap (a manifest row for the same name wins; that is the convergence path).
$LegacyAssetRetireOn = '2026-12-20'
$LegacyAssetNamePattern = '^(style|boot)\.[0-9a-f]{10}\.(css|js)$'
$LegacyAssetHardcoded = @(
    [pscustomobject]@{ Name = 'style.885ce0a604.css'; Expires = [datetime]$LegacyAssetRetireOn; Source = 'rel2-b-hardcoded' }
    [pscustomobject]@{ Name = 'boot.510d5a90dd.js'; Expires = [datetime]$LegacyAssetRetireOn; Source = 'rel2-b-hardcoded' }
)

function Get-ReleaseToday {
    # Repo docs / reports use Beijing dates (AGENTS.md section 12) while this host runs UTC-8,
    # so an overnight Beijing release would otherwise evaluate expiry one day early. Fall back
    # to the local date if the time zone id is unavailable.
    try {
        $bj = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), 'China Standard Time')
        if ($bj) { return $bj.Date }
    } catch { }
    return (Get-Date).Date
}

function Test-LegacyAssetName([string]$Name) {
    # Exact name only: no wildcards, no 'assets/' prefix, no path tricks.
    if (-not $Name) { return $false }
    if ($Name -match '[\*\?\[]') { return $false }
    if ($Name.StartsWith('assets/')) { return $false }
    return ($Name -match $LegacyAssetNamePattern)
}

function ConvertTo-ManifestDate([object]$Value) {
    # yyyy-MM-dd or $null (a single malformed row must not kill the keep list).
    if ($null -eq $Value) { return $null }
    try {
        return [datetime]::ParseExact([string]$Value, 'yyyy-MM-dd', [System.Globalization.CultureInfo]::InvariantCulture)
    } catch {
        return $null
    }
}

function Read-LegacyAssetManifest([string]$Path) {
    # Tolerant reader: a release must not be blocked by a missing / broken manifest, but every
    # problem is printed as a WARN by Show-LegacyAssetKeepList (silent loss of protection is
    # what REL6 exists to prevent). Wildcards are reported separately: they abort (exit 2).
    $res = @{ Exists = $false; Entries = @(); Rejected = @(); Problems = @(); HasWildcard = $false }
    if (-not (Test-Path -LiteralPath $Path)) {
        $res.Problems += ("manifest not found ({0}); only the hard-coded pair is protected - run deploy\collect_legacy_assets.ps1 before site\build.py" -f $Path)
        return $res
    }
    $res.Exists = $true
    try {
        $doc = (Get-Content -LiteralPath $Path -Encoding UTF8 -Raw) | ConvertFrom-Json
    } catch {
        $res.Problems += ("manifest is not valid JSON ({0}); ignored for this run" -f $_.Exception.Message)
        return $res
    }
    foreach ($e in @($doc.entries)) {
        if ($null -eq $e) { continue }
        $name = [string]$e.name
        if ($name -match '[\*\?\[]') {
            $res.HasWildcard = $true
            $res.Rejected += [pscustomobject]@{ Name = $name; Reason = 'wildcards are forbidden (exact hashed asset names only)' }
            continue
        }
        if (-not (Test-LegacyAssetName $name)) {
            $res.Rejected += [pscustomobject]@{ Name = $name; Reason = ('not an exact hashed asset name (want style|boot.<10 hex>.css|js): {0}' -f $LegacyAssetNamePattern) }
            continue
        }
        $exp = ConvertTo-ManifestDate $e.expires
        if ($null -eq $exp) {
            $res.Rejected += [pscustomobject]@{ Name = $name; Reason = ("bad expires '{0}' (want yyyy-MM-dd)" -f [string]$e.expires) }
            continue
        }
        $src = if ($e.source) { [string]$e.source } else { 'manifest' }
        $res.Entries += [pscustomobject]@{ Name = $name; Expires = $exp; Source = $src }
    }
    return $res
}

function Resolve-LegacyAssetKeepList([string]$Path) {
    # Merge: REL2-B hard-coded pair first, manifest second (manifest wins on the same name).
    # Partition into active (expires >= today, inclusive) / expired (ignored).
    $today = Get-ReleaseToday
    $map = [ordered]@{}
    foreach ($h in $LegacyAssetHardcoded) { $map[$h.Name] = $h }
    $man = Read-LegacyAssetManifest $Path
    foreach ($e in $man.Entries) { $map[$e.Name] = $e }
    $active = @()
    $expired = @()
    foreach ($name in @($map.Keys)) {
        $entry = $map[$name]
        if ($entry.Expires -ge $today) { $active += $entry } else { $expired += $entry }
    }
    $excludeArgs = @()
    foreach ($entry in $active) {
        $excludeArgs += '--exclude'
        $excludeArgs += ('assets/' + $entry.Name)
    }
    return @{
        ManifestPath = $Path
        Today        = $today
        Active       = $active
        Expired      = $expired
        Rejected     = $man.Rejected
        Problems     = $man.Problems
        HasWildcard  = $man.HasWildcard
        ExcludeArgs  = $excludeArgs
    }
}

function Show-LegacyAssetKeepList($Keep) {
    # Printed in BOTH -DryRun and real runs, before any upload / budget gate.
    Write-Host ("assets-keep: manifest = {0}" -f $Keep.ManifestPath)
    Write-Host ("assets-keep: today (Beijing) = {0:yyyy-MM-dd}; entries stay excluded through `expires` (inclusive)" -f $Keep.Today)
    foreach ($p in $Keep.Problems) { Write-Host ("WARN: assets-keep: {0}" -f $p) }
    foreach ($e in $Keep.Active) {
        Write-Host ("assets-keep:   keep    assets/{0}   expires {1:yyyy-MM-dd}   ({2})" -f $e.Name, $e.Expires, $e.Source)
    }
    foreach ($e in $Keep.Expired) {
        Write-Host ("assets-keep:   expired assets/{0}   expired {1:yyyy-MM-dd}   (ignored, no --exclude)" -f $e.Name, $e.Expires)
    }
    foreach ($e in $Keep.Rejected) {
        Write-Host ("assets-keep:   invalid {0}   ({1})   (ignored, no --exclude)" -f $e.Name, $e.Reason)
    }
    $wildcards = @($Keep.Active | Where-Object { $_.Name -match '[\*\?\[]' }).Count
    Write-Host ("assets-keep: {0} exact --exclude(s), {1} expired ignored, {2} invalid ignored, {3} wildcard(s)" -f $Keep.Active.Count, $Keep.Expired.Count, $Keep.Rejected.Count, $wildcards)
}

if (-not $ManifestPath) { $ManifestPath = Join-Path $Root 'data\legacy_assets.json' }
elseif (-not [System.IO.Path]::IsPathRooted($ManifestPath)) { $ManifestPath = Join-Path $Root $ManifestPath }
$AssetKeep = Resolve-LegacyAssetKeepList $ManifestPath
Show-LegacyAssetKeepList $AssetKeep
if ($AssetKeep.HasWildcard) {
    Write-Host 'ERROR: keep list contains a wildcard entry; refusing to publish with an unbounded --exclude set (fix data\legacy_assets.json).'
    exit 2
}
if ($ShowAssetExcludes) {
    Write-Host ("assets-keep: exclude args: {0}" -f ($AssetKeep.ExcludeArgs -join ' '))
    exit 0
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

    # REL6 (2026-11-24): the exclude set is now data-driven - see $AssetKeep resolved above
    # (data\legacy_assets.json + the REL2-B hard-coded pair). Why excludes at all: sites cached
    # by browsers before v1.0.0 (and any page from the previous release that still references a
    # hash-named asset) request files the newer build no longer ships; a plain sync would
    # DELETE them from R2 (remote-only objects) and turn those cached pages into 404s. The
    # excludes are exact names only, deliberately no wildcards (a wildcard would protect every
    # future hash-named file, silently grow the bucket and hide typos).
    # Also passed to BOTH `rclone check` runs below: the post-sync check is two-way, so once
    # site/dist stops shipping an excluded file a strict check reports it as a difference and
    # exits 1 (release failure) - proven by the REL2-B self-test and the REL6 self-test.
    $AssetExcludes = @($AssetKeep.ExcludeArgs)

    # -- T19 (2026-11-26): keep the 5 synthetic language-root keys alive -------------------
    # deploy/fix_fr_root.py writes R2 object keys "<lang>/" (fr/ ko/ ja/ cs/ lv/) AFTER the
    # sync, because Cloudflare Transform Rules only cover /, /zh/, /es/, /zh-hant/. Those
    # keys are not part of site/dist, so a plain sync treats them as extras and deletes them
    # -> the fallback re-PUTs them: +5 DELETE +5 PUT every release, net effect zero
    # (v1.2.5 log: `Deleted: 5 (files), 1.072 MiB`).
    # Pattern choice (measured with -DryRun against the live bucket, zero writes):
    #   * `--exclude "/fr/"`  = DIRECTORY pattern -> prunes the whole fr/ tree. Measured
    #     `Checks: 362,116 -> 362,076` (-40 = 5 langs x 8 root files) => future fr/*.html
    #     changes would silently stop uploading. REJECTED.
    #   * `--exclude "{{^fr/$}}"` = rclone REGEXP filter (the braces must be LITERAL DOUBLE
    #     braces - rclone only treats "{{...}}" as a regexp). Matches ONLY the object whose
    #     filter path is literally "fr/" (the marker key). Measured from Windows PowerShell
    #     5.1 with the 5 rules and WITHOUT the asset excludes: `Deleted: 6 (files)` (only the
    #     6 remote-only old hashed assets) / `Checks` 362,118 = 362,112 dist files + 6; with
    #     single braces `{^fr/$}` it was `Deleted: 11` (5 markers + 6 assets) => braces matter.
    #     NOTE: PowerShell's `-f` operator UNESCAPES `{{` to `{`, so the pattern must be built
    #     by concatenation (`'{{^' + $lang + '/$}}'`), not with `-f`.
    # Still "exact names only" in the REL6 sense: one literal key per rule, no wildcard that
    # could hide a typo or silently protect future files.
    # Also passed to BOTH `rclone check` runs: the post-sync check is two-way, so the kept-alive
    # keys would otherwise be reported as 5 differences and fail the release.
    $LangRootExcludes = @()
    foreach ($lang in $FallbackLangs) { $LangRootExcludes += @('--exclude', ('{{^' + $lang + '/$}}')) }
    # ASCII only on purpose: this script is launched via Windows PowerShell 5.1 (`-File`), which
    # decodes a BOM-less .ps1 as the system ANSI codepage; non-ASCII text here broke parsing
    # during T19 (UTF-8 bytes decoded as GBK produced a stray quote). Keep this file ASCII.
    Write-Host ("lang-root-keep: {0} exact --exclude(s): {1} (trailing-slash object keys, not in site/dist)" -f $FallbackLangs.Count, (($FallbackLangs | ForEach-Object { "$_/" }) -join ' '))

    if ($CheckOnly) {
        # --one-way: the bucket intentionally holds the synthetic language-root fallback
        # objects (fr/, ko/; not in site/dist), and may hold pre-sync extras that the next
        # sync deletes; a strict two-way check would always report those as differences
        # (2026-11-13: without --one-way, -CheckOnly exited 1 with `1 differences / 1 files
        # missing` on a healthy bucket, purely because of fr/).
        Write-Host ("check: {0} -> r2:{1} (size-only, one-way)" -f $Dist, $bucket)
        & $rclone check $Dist ("r2:{0}" -f $bucket) --size-only --one-way @confArgs @AssetExcludes @LangRootExcludes
        if ($LASTEXITCODE -ne 0) { Write-Host 'ERROR: rclone check failed'; exit 1 }
        Write-Host 'check: OK (size-only, one-way)'
        exit 0
    }

    # Q8 (2026-11-18): make the Class A write count and duration readable in the release log.
    # rclone 1.76 defaults `--stats-log-level` to INFO, so a REAL sync at the default NOTICE
    # log level prints no stats block at all: the v0.13.5 log (.tmp/sync-v0135.log, 16 lines)
    # has `0 differences / 137323 matching` from the verify step but no `Transferred:` line,
    # so the PUT count had to be inferred from the dist file count. (Under -DryRun rclone does
    # log a summary at NOTICE, which is why dry-run logs looked fine - real publishes did not.)
    # Pin both flags explicitly instead of relying on rclone defaults:
    #   --stats 60s             one stats block per minute (throughput / ETA on long syncs);
    #   --stats-log-level NOTICE  stats at NOTICE, i.e. visible without -v. Deliberately NOT
    #                           -v: that logs one INFO line per file (~117k lines for a full
    #                           sync) and buries the summary.
    # Logging only: file selection, checksums and transfer parameters are unchanged. Same
    # product, `-DryRun` planned file sets are identical before/after the change (evidence in
    # reports/2026-11-18-q5-q8-deploy.md).
    # How to read: the LAST `Transferred: N / N, 100%` line - N = files written this run
    # (planned files under -DryRun) ~= Class A PUTs (average 7.8 KB/file, far below the
    # multipart threshold, so 1 file = 1 PUT). Duration is the `Elapsed time:` line.
    # When nothing needs writing rclone prints only `Transferred: 0 B / 0 B` (no N/N line);
    # parse that as 0 PUT.
    $syncArgs = @('sync', $Dist, ("r2:{0}" -f $bucket), '--checksum',
                  '--transfers', $Transfers, '--checkers', $Transfers,
                  '--stats', '60s', '--stats-log-level', 'NOTICE') + $confArgs + $AssetExcludes + $LangRootExcludes
    # -- REL3 (2026-11-21): R2 Class A budget guard + PUT ledger ----------------
    # Free tier = 1M Class A ops/month; above it $4.50 per million, Cloudflare rounds UP
    # to the next million; projected > 1M needs the USER's approval (AGENTS.md section 6).
    # Gates (evaluated BEFORE any upload; -DryRun evaluates the same gates, uploads nothing):
    #   * month-to-date >= 900,000    -> stop, exit 3, report to Lead/human (no override);
    #   * planned > 50,000            -> needs explicit -ApproveLarge (Lead approval);
    #   * projected month >= 900,000  -> needs -ApproveLarge; >= 1,000,000 needs user approval.
    # Budget per publish = main-sync N + $BudgetExtra (17 assets PUTs + 5 lang-root PUTs).
    # T19 (2026-11-26) keeps the 5 language-root keys alive (see $LangRootExcludes), and
    # fix_fr_root.py now SKIPS a PUT when the remote object already matches (same md5+size),
    # so a normal release spends 17 + 0 = 17. $BudgetExtra stays 22 as a deliberate UPPER
    # BOUND (worst case: all 5 fallback objects missing again -> 5 PUTs), so the projection
    # can only over-estimate, never under-estimate.
    # Ledger = data/r2_put_ledger.jsonl, one JSON line per REAL sync (mode=real).
    # v1.0.0 / earlier usage is NOT backfilled (task-4: no history backfill) - reconcile the current
    # Cloudflare cycle by hand until the first full month of ledger data.
    $BudgetExtra = 22
    $FreeTier = 1000000
    $planLog = $null
    $syncLog = $null
    if (-not $LedgerPath) { $LedgerPath = Join-Path $Root 'data\r2_put_ledger.jsonl' }
    elseif (-not [System.IO.Path]::IsPathRooted($LedgerPath)) { $LedgerPath = Join-Path $Root $LedgerPath }
    $budget = Get-R2LedgerMonthTotal $LedgerPath
    Write-Host ("budget: month {0} = {1:N0} PUT ({2:N1}% of 1M free, ledger rows {3}); ledger={4}" -f $budget.Month, $budget.Total, (100.0 * $budget.Total / $FreeTier), $budget.Rows, $LedgerPath)
    if ($budget.Bad) { Write-Host ("WARN: ledger has {0} unparsable row(s), skipped (judgement unaffected)" -f $budget.Bad) }
    if ($budget.Total -ge 900000) {
        Write-Host ("ERROR: month-to-date {0:N0} PUT is >= 900,000 (1M free tier): STOP the release and report to Lead/human (release rule)." -f $budget.Total)
        Write-Host '       Projected > 1,000,000 needs the USER approval first; do not continue unapproved.'
        exit 3
    }
    # rclone writes its log itself (--log-file) so NOTICE stats never hit PowerShell's error
    # stream. On this host rclone.exe is denied writes under %TEMP% ("Failed to open log
    # file: Access is denied"), so keep the scratch logs in the gitignored repo .tmp\rclone\.
    $logDir = Join-Path $Root '.tmp\rclone'
    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    }
    $planLog = Join-Path $logDir ("rclone-plan-{0}-{1}.log" -f $PID, [guid]::NewGuid().ToString('N').Substring(0, 8))
    $syncLog = Join-Path $logDir ("rclone-sync-{0}-{1}.log" -f $PID, [guid]::NewGuid().ToString('N').Substring(0, 8))

    if ($DryRun) {
        # A dry run IS the planning pass: it yields the planned count, writes nothing, and
        # enforces the same budget gates (exit 3 instead of uploading).
        Write-Host ("sync: {0} -> r2:{1} (dry-run=True)" -f $Dist, $bucket)
        # rclone --log-file: NOTICE stats go to the file, NOT to PowerShell's error stream
        # (a native stderr line would terminate this script under $ErrorActionPreference='Stop').
        & $rclone @syncArgs --dry-run --log-file $planLog
        if ($LASTEXITCODE -ne 0) {
            Show-RcloneTail $planLog 'plan'
            Write-Host ("ERROR: rclone exit {0}" -f $LASTEXITCODE)
            exit 1
        }
        Write-RcloneSummary $planLog 'plan'
        $planned = Get-TransferredCount $planLog
        $projected = $budget.Total + $planned + $BudgetExtra
        Write-Host ("budget: planned={0:N0} + assets/fallback {1} -> projected month total {2:N0} PUT ({3:N1}% of 1M)" -f $planned, $BudgetExtra, $projected, (100.0 * $projected / $FreeTier))
        if ($planned -gt 50000 -and -not $ApproveLarge) {
            Write-Host ("ERROR: planned {0:N0} > 50,000: needs Lead approval + explicit -ApproveLarge (dry run uploaded nothing)." -f $planned)
            exit 3
        }
        if ($projected -ge 900000 -and -not $ApproveLarge) {
            Write-Host ("ERROR: projected month total {0:N0} >= 900,000: needs Lead approval + -ApproveLarge; >1,000,000 needs USER approval first." -f $projected)
            exit 3
        }
        if ($projected -ge $FreeTier) {
            Write-Host ("WARN: projected month total {0:N0} >= 1,000,000 (billed): USER approval must already exist and be recorded in the release report." -f $projected)
        }
        # REL2-B: the Cache-Control pass is a real `rclone copy`, so a dry run must not
        # execute it. Count locally so the operator still sees the planned PUTs (~17).
        $assetsDir = Join-Path $Dist 'assets'
        $assetCount = if (Test-Path $assetsDir) { @(Get-ChildItem -LiteralPath $assetsDir -File -Recurse).Count } else { 0 }
        Write-Host ("dry-run: skipped assets Cache-Control pass (would re-upload {0} files with --ignore-times --header-upload 'Cache-Control: public, max-age=300')" -f $assetCount)
    } else {
        # Real publish: planning pass first (dry-run, zero writes) so the gates can stop
        # BEFORE spending any Class A op. Console shows only the summary; full log in $planLog.
        Write-Host ("plan: {0} -> r2:{1} (dry-run planning pass, no writes)" -f $Dist, $bucket)
        & $rclone @syncArgs --dry-run --log-file $planLog
        if ($LASTEXITCODE -ne 0) {
            Show-RcloneTail $planLog 'plan'
            Write-Host ("ERROR: rclone planning pass exit {0}" -f $LASTEXITCODE)
            exit 1
        }
        Write-RcloneSummary $planLog 'plan'
        $planned = Get-TransferredCount $planLog
        $projected = $budget.Total + $planned + $BudgetExtra
        Write-Host ("budget: planned={0:N0} + assets/fallback {1} -> projected month total {2:N0} PUT ({3:N1}% of 1M)" -f $planned, $BudgetExtra, $projected, (100.0 * $projected / $FreeTier))
        if ($planned -gt 50000 -and -not $ApproveLarge) {
            Write-Host ("ERROR: planned {0:N0} > 50,000: needs Lead approval + explicit -ApproveLarge to continue." -f $planned)
            exit 3
        }
        if ($projected -ge 900000 -and -not $ApproveLarge) {
            Write-Host ("ERROR: projected month total {0:N0} >= 900,000: needs Lead approval + -ApproveLarge; >1,000,000 needs USER approval first." -f $projected)
            exit 3
        }
        if ($projected -ge $FreeTier) {
            Write-Host ("WARN: projected month total {0:N0} >= 1,000,000 (billed): USER approval must already exist and be recorded in the release report." -f $projected)
        }

        Write-Host ("sync: {0} -> r2:{1} (dry-run=False)" -f $Dist, $bucket)
        $syncStart = Get-Date
        & $rclone @syncArgs --log-file $syncLog
        if ($LASTEXITCODE -ne 0) {
            Show-RcloneTail $syncLog 'sync'
            Write-Host ("ERROR: rclone exit {0}" -f $LASTEXITCODE)
            exit 1
        }
        Write-RcloneSummary $syncLog 'sync'
        # REL3: record the real Class A PUTs immediately after upload success (they are spent
        # even if the post-sync check below fails). N = last `Transferred: N / N, 100%`.
        $filesWritten = Get-TransferredCount $syncLog
        $seconds = Get-ElapsedSeconds $syncLog
        if ($seconds -le 0) { $seconds = ((Get-Date) - $syncStart).TotalSeconds }
        $version = Get-ChangelogVersion
        try {
            Add-R2LedgerRow $LedgerPath $version $filesWritten $seconds
            Write-Host ("ledger: +{0:N0} files / {1:N1}s / {2} -> {3}" -f $filesWritten, $seconds, $version, $LedgerPath)
        } catch {
            Write-Host ("WARN: ledger append failed (publish succeeded; next budget check misses one row): {0}" -f $_.Exception.Message)
        }
    }

    if (-not $DryRun) {
        Write-Host 'upload done; verifying sizes'
        # REL6: pass the same exact excludes as the sync ($AssetExcludes, from the keep list
        # printed at the top). Excluded hash-named assets are remote-only by design (kept alive
        # for pages cached by the previous release); a two-way check would report each one as a
        # difference and exit 1, failing the release for the wrong reason.
        & $rclone check $Dist ("r2:{0}" -f $bucket) --size-only @confArgs @AssetExcludes @LangRootExcludes
        if ($LASTEXITCODE -ne 0) { Write-Host 'ERROR: rclone check failed'; exit 1 }

        # REL2-B (2026-11-20): second pass over assets/ only, with a 5-minute browser cache.
        # Why a separate pass: the main sync transfers only changed files, so unchanged
        # stable-name assets (assets/style.css / assets/boot.js, referenced by every
        # long-tail page since v1.0.0) would never get a Cache-Control header.
        # --ignore-times forces all ~17 files through (~17 Class A PUTs per publish, well
        # inside the <=3,000 target); 5 minutes caps the stale-UI window after a release.
        # copy (not sync) never deletes remote objects -> the excluded pre-v1.0.0 hashed
        # assets above stay untouched.
        # No stats block at NOTICE for this pass (--stats-log-level INFO, no -v): the LAST
        # `Transferred: N / N` line in the release log must stay the MAIN sync's count, which
        # is what the REL3 PUT ledger parses. This pass logs its own file count explicitly.
        $assetsDir = Join-Path $Dist 'assets'
        if (Test-Path $assetsDir) {
            $assetCount = @(Get-ChildItem -LiteralPath $assetsDir -File -Recurse).Count
            $assetArgs = @('copy', $assetsDir, ("r2:{0}/assets" -f $bucket),
                           '--ignore-times',
                           '--header-upload', 'Cache-Control: public, max-age=300',
                           '--stats-log-level', 'INFO') + $confArgs
            Write-Host ("assets: re-uploading {0} files with Cache-Control: public, max-age=300" -f $assetCount)
            & $rclone @assetArgs
            if ($LASTEXITCODE -ne 0) {
                Write-Host ("ERROR: rclone copy assets (Cache-Control) exit {0}" -f $LASTEXITCODE)
                exit 1
            }
        } else {
            Write-Host ("WARN: assets/ not found under {0}; Cache-Control pass skipped" -f $Dist)
        }

        # TEMPORARY FIX (approved 2026-11-13; generalised to a language list 2026-11-18):
        # Cloudflare Transform Rules currently only cover /, /zh/, /es/, /zh-hant/ - NOT
        # /fr/ and NOT /ko/ - so https://drugcrossref.com/fr/ and /ko/ 404 while
        # /fr/index.html and /ko/index.html are fine. We PUT <lang>/index.html as object
        # key "<lang>/" for every language in $FallbackLangs to work around it.
        # Those keys are not part of site/dist, so every sync deletes them -> replay after
        # each sync. FINAL FIX: add Transform Rules for each language (/fr/, /ko/, ...);
        # then drop this. A failure here only warns (upload success still exits 0), but the
        # language root 404s until fixed, and verify_live.py gates every LANG_ROOT
        # (incl. /fr/ and /ko/) - so a release cannot pass silently with a broken root.
        try {
            $fallbackPy = Resolve-FallbackPython
            if ($fallbackPy) {
                & $fallbackPy.Exe (Join-Path $PSScriptRoot 'fix_fr_root.py') --dist $Dist --langs ($FallbackLangs -join ',')
                if ($LASTEXITCODE -ne 0) {
                    Write-Host ("WARN: language-root fallback object(s) NOT written for {0} (fix_fr_root.py exit {1}, python={2}); https://drugcrossref.com/<lang>/ will 404 until the Transform Rule is added in Cloudflare." -f ($FallbackLangs -join ', '), $LASTEXITCODE, $fallbackPy.Exe)
                }
            } else {
                Write-Host ("WARN: language-root fallback NOT written for {0} (no usable python: tried `$env:PYTHON, python, py, runtime path; all missing or lacking botocore); those roots will 404 until the Transform Rules are added in Cloudflare." -f ($FallbackLangs -join ', '))
            }
        } catch {
            Write-Host ("WARN: language-root fallback not executed ({0}); {1} may 404 until the Transform Rules are added in Cloudflare." -f $_.Exception.Message, ($FallbackLangs -join ', '))
        }
    }
    Write-Host 'OK'
    exit 0
}
finally {
    if (Test-Path $conf) { Remove-Item $conf -Force -ErrorAction SilentlyContinue }
    # REL3: temp rclone logs (planning pass / real sync) are only used to parse counts.
    if ($planLog -and (Test-Path -LiteralPath $planLog)) {
        Remove-Item -LiteralPath $planLog -Force -ErrorAction SilentlyContinue
    }
    if ($syncLog -and (Test-Path -LiteralPath $syncLog)) {
        Remove-Item -LiteralPath $syncLog -Force -ErrorAction SilentlyContinue
    }
}
