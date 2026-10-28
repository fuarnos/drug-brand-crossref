<#
.SYNOPSIS
    Publish site/dist to the gh-pages branch that GitHub Pages serves.

.DESCRIPTION
    This is the only supported publish path. It exists because a publish that
    raced with site/build.py once pushed a gh-pages tree containing only
    assets/ - no index.html - and the whole site returned 404.

    The script refuses to publish unless the local build looks complete:
      * index.html exists and the search index is present
        (data/idx/core.json, or legacy data/index.json during the transition)
      * the file count is at least -MinFiles
      * no file was written in the last -StableSeconds seconds
      * no build.py / run_all.py process is running
      * no zero-byte files

    v0.6.6+ DEFAULT = INCREMENTAL: it keeps a local bare-ish clone of the
    gh-pages branch in .tmp\publish-opt\gh-pages-cache, refreshes it, mirrors
    dist into the work tree, commits on top of the current gh-pages HEAD and
    fast-forwards the branch. Unchanged files reuse existing git objects, so
    the push only transfers deltas (previously every release re-uploaded the
    whole 380-450 MB tree because the old flow created a fresh orphan commit
    and force-pushed it).

    Use -FullPush to fall back to the old "clean temp repo + force push" flow
    (emergency only; uploads the full tree).

    Both modes keep: staging isolation (source is re-checked after the copy),
    Pages build wait, homepage check, and -AutoRollback (incremental mode:
    force-push the previous commit back + re-verify).

.PARAMETER Message
    Commit message. Default: "Publish <version> (<n> files, incremental)".

.PARAMETER Dist
    Build directory. Default site/dist.

.PARAMETER CacheDir
    Local gh-pages mirror for incremental mode.
    Default .tmp\publish-opt\gh-pages-cache.

.PARAMETER MinFiles
    Minimum number of files in site/dist. Default 24000.

.PARAMETER StableSeconds
    Refuse to publish if the newest file is younger than this. Default 15.

.PARAMETER SkipVerify
    Push but do not wait for the Pages build / homepage check.

.PARAMETER FullPush
    Emergency fallback: old clean-repo + force-push flow (full upload).

.PARAMETER AutoRollback
    If the Pages build fails or the homepage check fails after an incremental
    push, force-push the previous gh-pages commit back and verify it again.

.PARAMETER KeepWork
    FullPush only: keep the temporary git repo after a successful publish.

.PARAMETER DryRun
    Run checks, stage the copy, create the commit and measure the estimated
    push pack, then reset the cache and stop before pushing (no public change).

.PARAMETER Force
    Bypass the file-count and file-age checks (not recommended).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1 -DryRun
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1 -FullPush

.NOTES
    Token: $env:GITHUB_TOKEN, or GITHUB_TOKEN=... in .env at the repo root.
    The token needs Contents: write on the repository.
    Manifest: .tmp\publish-opt\last-publish.json (mode/sha/changed files/pack size).
    Rollback of the whole script: deploy\publish.ps1.bak (restore + rerun).
#>
[CmdletBinding()]
param(
    [string]$Message = '',
    [string]$Dist = '',
    [string]$CacheDir = '',
    [int]$MinFiles = 24000,
    [int]$StableSeconds = 15,
    [switch]$SkipVerify,
    [switch]$FullPush,
    [switch]$AutoRollback,
    [switch]$KeepWork,
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$Root = Split-Path $PSScriptRoot -Parent
if (-not $Dist) { $Dist = Join-Path $Root 'site\dist' }
elseif (-not [System.IO.Path]::IsPathRooted($Dist)) { $Dist = Join-Path $Root $Dist }
$tmpRoot = Join-Path $Root '.tmp'
if (-not $CacheDir) { $CacheDir = Join-Path $tmpRoot 'publish-opt\gh-pages-cache' }
elseif (-not [System.IO.Path]::IsPathRooted($CacheDir)) { $CacheDir = Join-Path $Root $CacheDir }
$Work = $null
$Success = $false
$PagesUrl = $null
$PreviousSha = ''
$Sha = ''
$Mode = if ($FullPush) { 'full' } else { 'incremental' }
$ChangedFiles = @()
$ShortStat = ''
$PackBytes = 0
$ManifestPath = Join-Path $tmpRoot 'publish-opt\last-publish.json'
$PublishStarted = Get-Date

function Say([string]$Text) { Write-Host $Text }
function Step([string]$Text) {
    Write-Host ''
    Write-Host ("==> [{0:N0}s] {1}" -f ((Get-Date) - $script:PublishStarted).TotalSeconds, $Text) -ForegroundColor Cyan
}
function Fail([string]$Text) { throw $Text }

function Write-Manifest {
    try {
        New-Item -ItemType Directory -Path (Split-Path $ManifestPath -Parent) -Force | Out-Null
        $m = [ordered]@{
            at            = (Get-Date).ToString('o')
            mode          = $Mode
            version       = $Version
            previous_sha  = $PreviousSha
            gh_pages_sha  = $Sha
            changed_files = @($ChangedFiles).Count
            shortstat     = $ShortStat
            estimated_pack_bytes = $PackBytes
            elapsed_s     = [math]::Round(((Get-Date) - $PublishStarted).TotalSeconds, 1)
            pages_url     = $PagesUrl
            ok            = $Success
        }
        ($m | ConvertTo-Json -Depth 4) | Set-Content -Path $ManifestPath -Encoding UTF8
    } catch { Say ("warn: cannot write manifest: {0}" -f $_.Exception.Message) }
}

trap {
    Write-Host ''
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    if ($Work -and (Test-Path $Work)) { Write-Host ("work dir kept for inspection: " + $Work) }
    Write-Manifest
    exit 1
}

# ---------------------------------------------------------------- git + token
$Git = Join-Path $Root 'tools\git\cmd\git.exe'
if (-not (Test-Path $Git)) {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if (-not $cmd) { Fail 'git not found: install Git or keep the portable tools\git\cmd\git.exe' }
    $Git = $cmd.Source
}
Say "git: $Git"

$Token = $env:GITHUB_TOKEN
if (-not $Token) {
    $envFile = Join-Path $Root '.env'
    if (Test-Path $envFile) {
        $line = Get-Content $envFile | Where-Object { $_ -match '^GITHUB_TOKEN=' } | Select-Object -First 1
        if ($line) { $Token = ($line -replace '^GITHUB_TOKEN=', '').Trim() }
    }
}
if (-not $Token) { Fail 'GITHUB_TOKEN is not set (environment variable or .env)' }

$RemoteUrl = (& $Git -C $Root remote get-url origin)
if ($LASTEXITCODE -ne 0 -or -not $RemoteUrl) { Fail 'git remote "origin" is not configured' }
$RemoteUrl = $RemoteUrl.Trim()
Say "origin: $RemoteUrl"

$m = [regex]::Match($RemoteUrl, 'github\.com[:/](?<owner>[^/]+)/(?<repo>[^/]+?)(?:\.git)?$')
if (-not $m.Success) { Fail "origin is not a github.com repository URL: $RemoteUrl" }
$Owner = $m.Groups['owner'].Value
$Repo = $m.Groups['repo'].Value

# Push/fetch auth. The portable Git for Windows uses schannel by default, which
# can fail in restricted shells; its OpenSSL backend + bundled CA bundle is stable.
$b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$Token"))
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'never'
$caSrc = Join-Path (Split-Path (Split-Path $Git -Parent) -Parent) 'ucrt64\etc\ssl\certs\ca-bundle.crt'
if (Test-Path $caSrc) {
    $caDst = Join-Path $env:TEMP 'drug-brand-pages-ca.crt'
    Copy-Item $caSrc $caDst -Force
    $env:GIT_CONFIG_COUNT = '3'
    $env:GIT_CONFIG_KEY_0 = 'http.sslBackend'
    $env:GIT_CONFIG_VALUE_0 = 'openssl'
    $env:GIT_CONFIG_KEY_1 = 'http.sslCAInfo'
    $env:GIT_CONFIG_VALUE_1 = ($caDst -replace '\\', '/')
    $env:GIT_CONFIG_KEY_2 = 'http.extraHeader'
    $env:GIT_CONFIG_VALUE_2 = "Authorization: Basic $b64"
} else {
    $env:GIT_CONFIG_COUNT = '1'
    $env:GIT_CONFIG_KEY_0 = 'http.extraHeader'
    $env:GIT_CONFIG_VALUE_0 = "Authorization: Basic $b64"
}

# ------------------------------------------------------------- build checks
Step 'Checking local build'
if (-not (Test-Path (Join-Path $Dist 'index.html'))) {
    Fail 'site/dist/index.html is missing - the build is incomplete or still running'
}
$coreJson = Join-Path $Dist 'data\idx\core.json'
$legacyIndex = Join-Path $Dist 'data\index.json'
if (Test-Path $legacyIndex) {
    # Transition period ($env:WRITE_LEGACY_INDEX=1): legacy index.json is still written.
    if ((Get-Item $legacyIndex).Length -lt 5MB) { Fail 'site/dist/data/index.json is too small - build is incomplete' }
} else {
    # v0.6.1: core.json is the only search index (~27 MB raw / ~6 MB gzip; <10 MB raw = incomplete).
    if (-not (Test-Path $coreJson)) {
        Fail 'site/dist/data/idx/core.json is missing - the search index was not written (build incomplete)'
    }
    if ((Get-Item $coreJson).Length -lt 10MB) { Fail 'site/dist/data/idx/core.json is too small - build is incomplete' }
}

$files = @(Get-ChildItem $Dist -Recurse -File -Force)
$totalBytes = ($files | Measure-Object Length -Sum).Sum
$newest = $files | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$age = (Get-Date) - $newest.LastWriteTime
Say ("files: {0:N0}   size: {1:N1} MB   newest: {2}" -f $files.Count, ($totalBytes / 1MB), $newest.LastWriteTime)

$empty = @($files | Where-Object { $_.Length -eq 0 })
if ($empty.Count -gt 0) { Fail ("{0} zero-byte files in site/dist - build is incomplete" -f $empty.Count) }

if ($files.Count -lt $MinFiles -and -not $Force) {
    Fail ("site/dist has only {0:N0} files (min {1:N0}); the build looks partial. Use -Force only if this is intended." -f $files.Count, $MinFiles)
}

if ($age.TotalSeconds -lt $StableSeconds -and -not $Force) {
    Fail ("newest file was written {0:N0}s ago; wait {1}s so a running build cannot be captured. Use -Force to override." -f $age.TotalSeconds, $StableSeconds)
}

try {
    $running = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction Stop |
        Where-Object { $_.CommandLine -match 'site[\\/]build\.py|run_all\.py' })
    if ($running.Count -gt 0) {
        Fail ("a build is still running (python pid {0}); wait for it to finish" -f $running[0].ProcessId)
    }
} catch {
    Say 'warn: could not inspect running python processes'
}

# ------------------------------------------------------------ release notes
$Version = ''
$ReleaseDate = ''
$ReleaseBullets = @()
$changelog = Join-Path $Root 'CHANGELOG.md'
if (Test-Path $changelog) {
    $text = Get-Content $changelog -Raw -Encoding UTF8
    $rm = [regex]::Match($text, '(?m)^##\s+(v[0-9][^\s]*)\s*(?:\u2014|\u2013|-)\s*(\d{4}-\d{2}-\d{2})')
    if ($rm.Success) {
        $Version = $rm.Groups[1].Value
        $ReleaseDate = $rm.Groups[2].Value
        $rest = $text.Substring($rm.Index + $rm.Length)
        $next = [regex]::Match($rest, '(?m)^##\s+')
        if ($next.Success) { $rest = $rest.Substring(0, $next.Index) }
        $lines = $rest -split "`r?`n"
        $i = 0
        while ($i -lt $lines.Count -and $ReleaseBullets.Count -lt 5) {
            if ($lines[$i] -match '^-\s+(.+)$') {
                $b = $Matches[1]
                $i++
                while ($i -lt $lines.Count -and $lines[$i] -match '^\s{2,}(\S.*)$' -and $lines[$i] -notmatch '^\s*-\s+') {
                    $b += ' ' + $Matches[1].Trim()
                    $i++
                }
                $ReleaseBullets += ((($b -replace '\*\*', '') -replace '`', '').Trim())
            } else {
                $i++
            }
        }
    }
}
if ($Version) {
    Step ("Release notes: {0} - {1}" -f $Version, $ReleaseDate)
    foreach ($b in $ReleaseBullets) { Say ("  - " + $b) }
} else {
    Say 'warn: CHANGELOG.md has no "## vX - YYYY-MM-DD" section; using a generic commit message'
}

if (-not $Message) {
    if ($Version) {
        $Message = "Publish $Version ($($files.Count) files, $Mode)"
    } else {
        $Message = 'Publish site {0} ({1:N0} files, {2})' -f (Get-Date -Format 'yyyy-MM-dd HH:mm'), $files.Count, $Mode
    }
}

# ============================================================================
#  INCREMENTAL MODE (default): commit on top of the current gh-pages HEAD
# ============================================================================
if ($Mode -eq 'incremental') {
    New-Item -ItemType Directory -Path (Split-Path $CacheDir -Parent) -Force | Out-Null

    Step 'Updating the gh-pages cache'
    if (-not (Test-Path (Join-Path $CacheDir '.git'))) {
        Say ("cache: {0} (one-time bootstrap: full clone of gh-pages)" -f $CacheDir)
        if (Test-Path $CacheDir) { Remove-Item $CacheDir -Recurse -Force }
        & $Git -c core.longpaths=true clone -q --branch gh-pages --single-branch $RemoteUrl $CacheDir
        if ($LASTEXITCODE -ne 0) {
            Fail 'cannot clone gh-pages for incremental mode (network/auth?); retry or use -FullPush'
        }
    } else {
        & $Git -C $CacheDir fetch -q origin gh-pages
        if ($LASTEXITCODE -ne 0) { Fail 'git fetch gh-pages failed; retry or use -FullPush' }
        & $Git -C $CacheDir checkout -q -f -B gh-pages origin/gh-pages
        if ($LASTEXITCODE -ne 0) { Fail 'git checkout gh-pages failed' }
        & $Git -C $CacheDir reset --hard -q origin/gh-pages
        & $Git -C $CacheDir clean -fdxq
    }
    Say ("cache: {0}" -f $CacheDir)
    & $Git -C $CacheDir config user.name 'drug-catalog'
    & $Git -C $CacheDir config user.email 'drug-catalog@users.noreply.github.com'
    & $Git -C $CacheDir config core.autocrlf false
    & $Git -C $CacheDir config core.longpaths true
    # Incremental commits add up to ~60k loose objects; automatic gc/repack after
    # each commit would copy the whole 390 MB tree and dominate publish time.
    # The push builds its own pack from the loose objects, so keep auto-gc off.
    & $Git -C $CacheDir config gc.auto 0
    & $Git -C $CacheDir config maintenance.auto false

    $PreviousSha = (& $Git -C $CacheDir rev-parse HEAD).Trim()
    Say ("previous gh-pages commit: {0}" -f $PreviousSha)

    Step 'Mirroring site/dist into the cache work tree'
    $cacheGitDir = Join-Path $CacheDir '.git'
    & robocopy $Dist $CacheDir /MIR /XD $cacheGitDir /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    $rc = $LASTEXITCODE
    if ($rc -ge 8) { Fail ("robocopy failed with exit code {0}" -f $rc) }
    if (-not (Test-Path $cacheGitDir)) { Fail 'cache .git disappeared during mirroring (robocopy /XD failed); re-run bootstrap' }
    # Keep the historical published convention: .nojekyll is present but empty.
    Set-Content -Path (Join-Path $CacheDir '.nojekyll') -Value '' -Encoding ascii -NoNewline

    $staged = @(Get-ChildItem $CacheDir -Recurse -File -Force |
        Where-Object { $_.FullName -notmatch '\\\.git\\' })
    Say ("staged: {0:N0} files" -f $staged.Count)
    if ($staged.Count -lt $files.Count) { Fail 'staged copy is smaller than site/dist' }

    # A build can start while robocopy is running; re-check the source after the copy.
    $files2 = @(Get-ChildItem $Dist -Recurse -File -Force)
    $newest2 = $files2 | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $bytes2 = ($files2 | Measure-Object Length -Sum).Sum
    if ($files2.Count -ne $files.Count -or $newest2.LastWriteTime -ne $newest.LastWriteTime -or $bytes2 -ne $totalBytes) {
        Fail 'site/dist changed while copying (a build started?); run the publish again when the build is idle'
    }

    Step 'Committing changes on top of gh-pages'
    & $Git -C $CacheDir add -A
    if ($LASTEXITCODE -ne 0) { Fail 'git add failed' }
    $ChangedFiles = @(& $Git -C $CacheDir diff --cached --name-only)
    if ($ChangedFiles.Count -eq 0) {
        Say 'no file changes vs the current gh-pages tree - nothing to publish'
        $Success = $true
        Write-Manifest
        exit 0
    }
    $ShortStat = (& $Git -C $CacheDir diff --cached --shortstat).Trim()
    Say ("changed: {0:N0} files ({1})" -f $ChangedFiles.Count, $ShortStat)

    & $Git -C $CacheDir commit -q -m $Message
    if ($LASTEXITCODE -ne 0) { Fail 'git commit failed' }
    $Sha = (& $Git -C $CacheDir rev-parse HEAD).Trim()
    Say ("commit: {0}" -f $Sha)

    # Estimate the push pack exactly like `git push` does (thin pack against the
    # previous gh-pages tree). This is the number the release report records.
    Step 'Estimating the incremental push pack'
    New-Item -ItemType Directory -Path (Split-Path $ManifestPath -Parent) -Force | Out-Null
    $revFile = Join-Path $tmpRoot 'publish-opt\.pack-revs.txt'
    $packFile = Join-Path $tmpRoot 'publish-opt\estimated-push.pack'
    $packErr = Join-Path $tmpRoot 'publish-opt\estimated-push.err'
    [IO.File]::WriteAllText($revFile, "$Sha`n^$PreviousSha`n")
    $cmdLine = '"{0}" -C "{1}" pack-objects --stdout --revs --thin --delta-base-offset < "{2}" > "{3}" 2> "{4}"' -f `
        $Git, $CacheDir, $revFile, $packFile, $packErr
    & cmd.exe /c $cmdLine | Out-Null
    if ((Test-Path $packFile) -and (Get-Item $packFile).Length -gt 128) {
        $PackBytes = (Get-Item $packFile).Length
        Say ("estimated push pack: {0:N2} MB (thin, vs {1:N1} MB full tree)" -f ($PackBytes / 1MB), ($totalBytes / 1MB))
    } else {
        Say 'warn: could not estimate push pack size'
        if (Test-Path $packErr) { Get-Content $packErr | Select-Object -First 3 | ForEach-Object { Say ("  " + $_) } }
    }

    if ($DryRun) {
        Say ''
        Say ("dry run: created commit {0} then reset; not pushing" -f $Sha.Substring(0, 8))
        Say ("dry run: previous {0}; changed {1:N0} files; estimated pack {2:N2} MB" -f `
            $PreviousSha.Substring(0, 8), $ChangedFiles.Count, ($PackBytes / 1MB))
        & $Git -C $CacheDir reset --hard -q $PreviousSha
        & $Git -C $CacheDir clean -fdxq
        $Success = $true
        Write-Manifest
        exit 0
    }

    Step 'Pushing incremental commit to gh-pages'
    & $Git -C $CacheDir push --progress origin HEAD:refs/heads/gh-pages
    if ($LASTEXITCODE -ne 0) {
        & $Git -C $CacheDir fetch -q origin gh-pages
        $remoteHead = (& $Git -C $CacheDir rev-parse origin/gh-pages).Trim()
        if ($remoteHead -ne $PreviousSha) {
            Fail ("remote gh-pages moved while publishing ({0} -> {1}); rerun the publish" -f $PreviousSha, $remoteHead)
        }
        Fail ("git push failed with exit code {0}" -f $LASTEXITCODE)
    }
    Say 'pushed: gh-pages (incremental)'
}

# ============================================================================
#  FULL MODE (-FullPush): legacy clean-repo + force push (uploads everything)
# ============================================================================
if ($Mode -eq 'full') {
    Step 'Staging a clean copy'
    New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null
    $Work = Join-Path $tmpRoot ('pages-publish-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Path $Work -Force | Out-Null
    Say "work: $Work"

    & robocopy $Dist $Work /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    $rc = $LASTEXITCODE
    if ($rc -ge 8) { Fail ("robocopy failed with exit code {0}" -f $rc) }

    # GitHub Pages would otherwise run Jekyll over 25k files on every deploy.
    Set-Content -Path (Join-Path $Work '.nojekyll') -Value '' -Encoding ascii -NoNewline

    $staged = @(Get-ChildItem $Work -Recurse -File -Force)
    Say ("staged: {0:N0} files" -f $staged.Count)
    if ($staged.Count -lt $files.Count) { Fail 'staged copy is smaller than site/dist' }

    $files2 = @(Get-ChildItem $Dist -Recurse -File -Force)
    $newest2 = $files2 | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $bytes2 = ($files2 | Measure-Object Length -Sum).Sum
    if ($files2.Count -ne $files.Count -or $newest2.LastWriteTime -ne $newest.LastWriteTime -or $bytes2 -ne $totalBytes) {
        Fail 'site/dist changed while copying (a build started?); run the publish again when the build is idle'
    }

    Step 'Committing'
    & $Git -C $Work init -q
    & $Git -C $Work config user.name 'drug-catalog'
    & $Git -C $Work config user.email 'drug-catalog@users.noreply.github.com'
    & $Git -C $Work config core.autocrlf false
    & $Git -C $Work config core.longpaths true

    & $Git -C $Work add -A
    if ($LASTEXITCODE -ne 0) { Fail 'git add failed' }

    & $Git -C $Work commit -q -m $Message
    if ($LASTEXITCODE -ne 0) { Fail 'git commit failed' }
    $Sha = (& $Git -C $Work rev-parse HEAD).Trim()
    Say ("commit: {0}" -f $Sha)

    if ($DryRun) {
        Say ''
        Say ("dry run: committed {0}; not pushing (full mode, full upload expected)" -f $Sha)
        if (-not $KeepWork) { Remove-Item $Work -Recurse -Force }
        $Success = $true
        Write-Manifest
        exit 0
    }

    & $Git -C $Work remote add origin $RemoteUrl
    if ($LASTEXITCODE -ne 0) { Fail 'git remote add failed' }

    Step 'Pushing to gh-pages (full)'
    & $Git -C $Work push --force origin 'HEAD:refs/heads/gh-pages'
    if ($LASTEXITCODE -ne 0) { Fail ("git push failed with exit code {0}" -f $LASTEXITCODE) }
    Say 'pushed: gh-pages (full)'
}

# ---------------------------------------------------------------- verify
function Test-Homepage([string]$Url) {
    for ($i = 0; $i -lt 12; $i++) {
        try {
            $u = '{0}?v={1}' -f $Url.TrimEnd('/'), [DateTimeOffset]::Now.ToUnixTimeSeconds()
            $r = Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec 30
            if ($r.StatusCode -eq 200 -and $r.Content -match 'Medicine Brand Cross-Reference') { return $true }
        } catch { }
        Start-Sleep -Seconds 5
    }
    return $false
}

function Wait-PagesBuild([string]$CommitSha, $Headers, [string]$Url) {
    $built = $false
    $deadline = (Get-Date).AddMinutes(8)
    while ((Get-Date) -lt $deadline) {
        try {
            $builds = @(Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo/pages/builds?per_page=5" -Headers $Headers -TimeoutSec 30)
            foreach ($b in $builds) {
                if ($b.commit -eq $CommitSha) {
                    Say ("build {0} {1}" -f $b.commit.Substring(0, 8), $b.status)
                    if ($b.status -eq 'built') { return $true }
                    if ($b.status -eq 'errored') { return $false }
                    break
                }
            }
        } catch {
            Say ("warn: build query failed: {0}" -f $_.Exception.Message)
        }
        Start-Sleep -Seconds 10
    }
    return $false
}

function Invoke-Rollback([string]$ToSha, $Headers, [string]$Url) {
    Step ("ROLLBACK: force-pushing gh-pages back to {0}" -f $ToSha.Substring(0, 8))
    if (-not (Test-Path (Join-Path $CacheDir '.git'))) { Say 'warn: no incremental cache, cannot roll back automatically'; return $false }
    & $Git -C $CacheDir push --force origin ("{0}:refs/heads/gh-pages" -f $ToSha)
    if ($LASTEXITCODE -ne 0) { Say 'ERROR: rollback push failed'; return $false }
    Say 'rolled back: gh-pages'
    $built = Wait-PagesBuild $ToSha $Headers $Url
    if (-not $built) { Say 'ERROR: rollback Pages build failed/timed out'; return $false }
    $ok = Test-Homepage $Url
    if ($ok) { Say 'rollback verified: homepage 200 OK' } else { Say 'ERROR: rollback homepage check failed' }
    return $ok
}

$VerifyError = ''
$RolledBack = $false
if ($SkipVerify) {
    Say 'skipping Pages verification (-SkipVerify)'
    $PagesUrl = "https://$Owner.github.io/$Repo/"
} else {
    Step 'Waiting for the GitHub Pages build'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $headers = @{
        Authorization = "Bearer $Token"
        'User-Agent' = 'drug-brand-publish'
        Accept = 'application/vnd.github+json'
    }
    try {
        $pages = Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo/pages" -Headers $headers -TimeoutSec 30
        $PagesUrl = $pages.html_url
    } catch {
        Say ("warn: cannot read Pages settings: {0}" -f $_.Exception.Message)
        $PagesUrl = "https://$Owner.github.io/$Repo/"
    }
    Say "site: $PagesUrl"

    $built = Wait-PagesBuild $Sha $headers $PagesUrl
    if (-not $built) { $VerifyError = 'Pages build failed or timed out waiting for it (8 min)' }

    if (-not $VerifyError) {
        Step 'Checking the homepage'
        $ok = Test-Homepage $PagesUrl
        if ($ok) { Say "homepage: 200 OK" }
        else { $VerifyError = "homepage did not return 200 with expected content: $PagesUrl" }
    }

    if ($VerifyError) {
        if ($AutoRollback -and $PreviousSha) {
            $RolledBack = Invoke-Rollback $PreviousSha $headers $PagesUrl
        }
        Fail ($VerifyError + $(if ($RolledBack) { ' (rolled back to ' + $PreviousSha.Substring(0, 8) + ')' }
                               elseif ($PreviousSha) { ' (previous gh-pages commit: ' + $PreviousSha + '; rerun with -AutoRollback to restore it)' }
                               else { '' }))
    }
}

$Success = $true
Write-Manifest
Say ''
Say ("Done. {0}" -f $PagesUrl)
Say ("release notes: {0}/whats-new.html" -f $PagesUrl.TrimEnd('/'))
Say ("commit {0} on gh-pages ({1} mode)" -f $Sha, $Mode)
if ($PackBytes -gt 0) { Say ("estimated push pack: {0:N2} MB" -f ($PackBytes / 1MB)) }
Say ("manifest: {0}" -f $ManifestPath)

if (-not $KeepWork -and $Work -and (Test-Path $Work)) {
    Remove-Item $Work -Recurse -Force
}
exit 0
