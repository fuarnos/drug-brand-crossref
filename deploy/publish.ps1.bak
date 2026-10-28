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

    It then copies dist to a clean temporary repo, commits, force-pushes
    gh-pages, waits for the GitHub Pages build, and checks the homepage.

.PARAMETER Message
    Commit message. Default: "Publish site <yyyy-MM-dd HH:mm> (<n> files)".

.PARAMETER MinFiles
    Minimum number of files in site/dist. Default 24000.

.PARAMETER StableSeconds
    Refuse to publish if the newest file is younger than this. Default 15.

.PARAMETER SkipVerify
    Push but do not wait for the Pages build / homepage check.

.PARAMETER KeepWork
    Keep the temporary git repo after a successful publish (debugging).

.PARAMETER DryRun
    Run checks, stage and commit, then stop before pushing (no public change).

.PARAMETER Force
    Bypass the file-count and file-age checks (not recommended).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File deploy\publish.ps1

.NOTES
    Token: $env:GITHUB_TOKEN, or GITHUB_TOKEN=... in .env at the repo root.
    The token needs Contents: write on the repository.
#>
[CmdletBinding()]
param(
    [string]$Message = '',
    [string]$Dist = '',
    [int]$MinFiles = 24000,
    [int]$StableSeconds = 15,
    [switch]$SkipVerify,
    [switch]$KeepWork,
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$Root = Split-Path $PSScriptRoot -Parent
if (-not $Dist) { $Dist = Join-Path $Root 'site\dist' }
elseif (-not [System.IO.Path]::IsPathRooted($Dist)) { $Dist = Join-Path $Root $Dist }
$Work = $null
$Success = $false
$PagesUrl = $null

function Say([string]$Text) { Write-Host $Text }
function Step([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Fail([string]$Text) { throw $Text }

trap {
    Write-Host ''
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    if ($Work -and (Test-Path $Work)) { Write-Host ("work dir kept for inspection: " + $Work) }
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

# --------------------------------------------------------------- stage copy
Step 'Staging a clean copy'
$tmpRoot = Join-Path $Root '.tmp'
if (-not (Test-Path $tmpRoot)) { New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null }
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

# A build can start while robocopy is running; re-check the source after the copy.
$files2 = @(Get-ChildItem $Dist -Recurse -File -Force)
$newest2 = $files2 | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$bytes2 = ($files2 | Measure-Object Length -Sum).Sum
if ($files2.Count -ne $files.Count -or $newest2.LastWriteTime -ne $newest.LastWriteTime -or $bytes2 -ne $totalBytes) {
    Fail 'site/dist changed while copying (a build started?); run the publish again when the build is idle'
}

# ------------------------------------------------------------------ commit
Step 'Committing'
& $Git -C $Work init -q
& $Git -C $Work config user.name 'drug-catalog'
& $Git -C $Work config user.email 'drug-catalog@users.noreply.github.com'
& $Git -C $Work config core.autocrlf false
& $Git -C $Work config core.longpaths true

& $Git -C $Work add -A
if ($LASTEXITCODE -ne 0) { Fail 'git add failed' }

if (-not $Message) {
    if ($Version) {
        $Message = "Publish $Version ($($files.Count) files)"
    } else {
        $Message = 'Publish site {0} ({1:N0} files)' -f (Get-Date -Format 'yyyy-MM-dd HH:mm'), $files.Count
    }
}
& $Git -C $Work commit -q -m $Message
if ($LASTEXITCODE -ne 0) { Fail 'git commit failed' }
$Sha = (& $Git -C $Work rev-parse HEAD).Trim()
Say ("commit: {0}" -f $Sha)

if ($DryRun) {
    Say ''
    Say ("dry run: committed {0}; not pushing" -f $Sha)
    if (-not $KeepWork) { Remove-Item $Work -Recurse -Force }
    exit 0
}

& $Git -C $Work remote add origin $RemoteUrl
if ($LASTEXITCODE -ne 0) { Fail 'git remote add failed' }

# -------------------------------------------------------------------- push
Step 'Pushing to gh-pages'
$b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$Token"))
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'never'

# The portable Git for Windows in tools\git uses schannel by default, which can
# fail in restricted shells; its OpenSSL backend + bundled CA bundle is stable.
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

& $Git -C $Work push --force origin 'HEAD:refs/heads/gh-pages'
if ($LASTEXITCODE -ne 0) { Fail ("git push failed with exit code {0}" -f $LASTEXITCODE) }
Say 'pushed: gh-pages'

# ---------------------------------------------------------------- verify
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

    $built = $false
    $deadline = (Get-Date).AddMinutes(8)
    while ((Get-Date) -lt $deadline) {
        try {
            $builds = @(Invoke-RestMethod -Uri "https://api.github.com/repos/$Owner/$Repo/pages/builds?per_page=1" -Headers $headers -TimeoutSec 30)
            if ($builds.Count -gt 0) {
                $b = $builds[0]
                Say ("build {0} {1}" -f $b.commit.Substring(0, 8), $b.status)
                if ($b.commit -eq $Sha -and $b.status -eq 'built') { $built = $true; break }
                if ($b.commit -eq $Sha -and $b.status -eq 'errored') {
                    Fail ("Pages build failed: {0}" -f $b.error.message)
                }
            }
        } catch {
            Say ("warn: build query failed: {0}" -f $_.Exception.Message)
        }
        Start-Sleep -Seconds 10
    }
    if (-not $built) { Fail 'timed out waiting for the Pages build (8 min)' }

    Step 'Checking the homepage'
    $ok = $false
    for ($i = 0; $i -lt 12; $i++) {
        try {
            $u = '{0}?v={1}' -f $PagesUrl.TrimEnd('/'), [DateTimeOffset]::Now.ToUnixTimeSeconds()
            $r = Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec 30
            if ($r.StatusCode -eq 200 -and $r.Content -match 'Medicine Brand Cross-Reference') {
                Say ("homepage: 200 OK")
                $ok = $true
                break
            }
        } catch { }
        Start-Sleep -Seconds 5
    }
    if (-not $ok) { Fail "homepage did not return 200 with expected content: $PagesUrl" }
}

$Success = $true
Say ''
Say ("Done. {0}" -f $PagesUrl)
Say ("release notes: {0}/whats-new.html" -f $PagesUrl.TrimEnd('/'))
Say ("commit {0} on gh-pages" -f $Sha)

if (-not $KeepWork -and $Work -and (Test-Path $Work)) {
    Remove-Item $Work -Recurse -Force
}
exit 0
