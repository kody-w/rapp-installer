# RAPP Brainstem Installer for Windows
# Usage: irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.ps1 | iex
# Pin a version: $env:BRAINSTEM_VERSION = "0.6.9"; irm https://raw.githubusercontent.com/kody-w/rapp-installer/main/install.ps1 | iex
#
# Works on a factory Windows 11 install — auto-installs Python, Git, and GitHub CLI via winget.

$ErrorActionPreference = "Stop"

# Force TLS 1.2 for every web request in this session. Stock Windows PowerShell 5.1
# on older builds negotiates TLS 1.0 by default, which GitHub and raw.githubusercontent
# now refuse — the download would fail with an opaque "could not create SSL/TLS secure
# channel". Additive and harmless where 1.2 is already the default.
try {
    [Net.ServicePointManager]::SecurityProtocol = `
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {}

$BRAINSTEM_HOME = "$env:USERPROFILE\.brainstem"
$BRAINSTEM_BIN = "$env:USERPROFILE\.local\bin"
$REPO_URL = "https://github.com/kody-w/rapp-installer.git"
$REMOTE_VERSION_URL = "https://raw.githubusercontent.com/kody-w/rapp-installer/main/rapp_brainstem/VERSION"
$VENV_DIR = "$env:USERPROFILE\.brainstem\venv"

# Optional version pin: a release tag in any form we ship - 0.6.14, v0.6.14 or the
# release tag brainstem-v0.6.14 - never a branch or a commit. The advertised
# `irm ... | iex` one-liner cannot pass script arguments, so the pin can come from the
# environment:
#   $env:BRAINSTEM_VERSION = "0.6.14"; irm https://.../install.ps1 | iex
# or from `--version`, which wins over the variable:
#   & ([scriptblock]::Create((irm https://.../install.ps1))) --version v0.6.14
# Surrounding whitespace is dropped first (the characters install.sh trims); an empty
# --version is then refused rather than silently installing main.
function Get-PinRequest {
    param([object[]]$ArgList, [string]$EnvValue)
    $space = [char[]]@(9, 10, 11, 12, 13, 32)
    $pin = @{ Version = ""; Source = ""; Error = "" }
    $fromEnv = "$EnvValue".Trim($space)
    if ($fromEnv) {
        $pin.Version = $fromEnv
        $pin.Source = "BRAINSTEM_VERSION"
    }
    for ($i = 0; $i -lt $ArgList.Count; $i++) {
        if ([string]$ArgList[$i] -eq "--version") {
            $value = ""
            if (($i + 1) -lt $ArgList.Count) { $value = ([string]$ArgList[$i + 1]).Trim($space) }
            if ($value) {
                $pin.Version = $value
                $pin.Source = "--version"
            } else {
                $pin.Error = "--version needs a value, e.g. --version 0.6.9"
            }
            $i++
        }
    }
    return $pin
}
$PIN_REQUEST = Get-PinRequest -ArgList @($args) -EnvValue $env:BRAINSTEM_VERSION
$PIN_VERSION = $PIN_REQUEST.Version
# The release tag and commit the pin resolved to on the remote (Main sets them).
$script:PIN_TAG = $null
$script:PIN_COMMIT = $null
# The kernel ("grail") files a pinned install must reproduce byte-for-byte: the set
# RAPP's KERNEL_PIN.json freezes by SHA-256.
$KERNEL_FILES = @("rapp_brainstem/brainstem.py", "rapp_brainstem/agents/basic_agent.py", "rapp_brainstem/VERSION")
# User state the source tree holds outside git (in rapp_brainstem\): soul, config, tokens
# and session, the LAN secret, the model pick, voice config, memories and remote agents
# (custom agents are handled with them). A switch leaves it in place; a re-clone over a
# broken install (src without .git) carries it over (Save-UserState / Restore-UserState).
$USER_STATE_FILES = @("soul.md", ".env", ".copilot_token", ".copilot_session", ".brainstem_secret", ".brainstem_model", "voice.zip")
$USER_STATE_DIRS = @(".brainstem_data", ".remote_agents")

function Print-Banner {
    Write-Host ""
    Write-Host "  🧠 RAPP Brainstem" -ForegroundColor Cyan
    Write-Host "  Local-first AI agent server" -ForegroundColor Gray
    Write-Host "  Powered by GitHub Copilot — no API keys needed" -ForegroundColor Gray
    Write-Host ""
}

function Compare-SemVer {
    param([string]$Local, [string]$Remote)
    $lParts = $Local.Split('.')
    $rParts = $Remote.Split('.')
    for ($i = 0; $i -lt [Math]::Max($lParts.Length, $rParts.Length); $i++) {
        $lv = if ($i -lt $lParts.Length) { [int]$lParts[$i] } else { 0 }
        $rv = if ($i -lt $rParts.Length) { [int]$rParts[$i] } else { 0 }
        if ($rv -gt $lv) { return 1 }   # remote is newer
        if ($rv -lt $lv) { return -1 }  # local is newer
    }
    return 0  # equal
}

function Check-ForUpgrade {
    $versionFile = "$BRAINSTEM_HOME\src\rapp_brainstem\VERSION"

    if (-not (Test-Path $versionFile)) { return $true }

    $localVersion = (Get-Content $versionFile -Raw).Trim()

    try {
        $remoteVersion = (Invoke-WebRequest -Uri $REMOTE_VERSION_URL -UseBasicParsing -TimeoutSec 10).Content.Trim()
    } catch {
        Write-Host "  [!] Could not check remote version — upgrading anyway" -ForegroundColor Yellow
        return $true
    }

    Write-Host "  Local version:  $localVersion" -ForegroundColor Cyan
    Write-Host "  Remote version: $remoteVersion" -ForegroundColor Cyan

    if ($localVersion -eq $remoteVersion) {
        Write-Host ""
        Write-Host "  [OK] Already up to date (v$localVersion)" -ForegroundColor Green
        Write-Host ""
        return $false
    }

    $cmp = Compare-SemVer -Local $localVersion -Remote $remoteVersion
    if ($cmp -eq 1) {
        Write-Host "  [..] Upgrade available: $localVersion -> $remoteVersion" -ForegroundColor Yellow
        return $true
    }

    Write-Host ""
    Write-Host "  [OK] Already up to date (v$localVersion)" -ForegroundColor Green
    Write-Host ""
    return $false
}

function Install-WithWinget {
    param([string]$PackageId, [string]$Name)
    Write-Host "  [..] Installing $Name via winget..." -ForegroundColor Yellow
    winget install --id $PackageId --accept-source-agreements --accept-package-agreements --silent 2>&1 | Out-Null
    # Refresh PATH for this session
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

function Resolve-PythonExe {
    # Return a real Python 3 executable. Prefer the one Check-Prerequisites already
    # validated ($script:PythonExe); otherwise probe — this matters on the
    # "already up to date" fast path, which skips Check-Prerequisites and would
    # otherwise fall back to a bare "python" that may be the Windows Store alias
    # stub (it prints "Python was not found" and opens the Store instead of running).
    if ($script:PythonExe) { return $script:PythonExe }
    foreach ($cmd in @("python3", "python")) {
        try {
            $out = & $cmd --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $out -match "Python 3\.(\d+)") {
                $script:PythonExe = $cmd
                return $cmd
            }
        } catch {}
    }
    $direct = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    if (Test-Path $direct) { $script:PythonExe = $direct; return $direct }
    return "python"
}

function Get-VenvPython {
    # Path to the venv interpreter (Windows layout: venv\Scripts\python.exe).
    return "$VENV_DIR\Scripts\python.exe"
}

function Resolve-RunPython {
    # The interpreter used to install deps, check deps, and launch the server: the
    # venv python when it exists (issue #29 — install and launch must resolve the
    # SAME interpreter), otherwise the system python as a safe fallback.
    $venvPy = Get-VenvPython
    if (Test-Path $venvPy) { return $venvPy }
    return (Resolve-PythonExe)
}

function Test-PipWorks {
    param([string]$Py)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Py -m pip --version 2>&1 | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Ensure-Pip {
    # A found Python is NOT guaranteed to have pip. Corp-managed images and
    # stripped/partial installs ship a working python.exe with no pip module —
    # seen in the wild on a fresh Windows 11 machine: every pip call printed
    # "No module named pip", then the server died at `import requests` behind a
    # dead localhost:7071 browser tab. Bootstrap order: ensurepip (stdlib,
    # works offline, restores the pip bundled with Python) -> get-pip.py (network).
    # Returns $true only when `python -m pip` actually works.
    $py = Resolve-PythonExe
    if (Test-PipWorks $py) { return $true }

    Write-Host "  [..] Python has no pip — bootstrapping via ensurepip..." -ForegroundColor Yellow
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        # Write-Host, not bare pipeline output: Ensure-Pip's return value is its
        # pipeline — stray tool output here would corrupt the caller's boolean.
        & $py -m ensurepip --upgrade --default-pip 2>&1 | ForEach-Object { Write-Host "$_" }
    } catch {
    } finally {
        $ErrorActionPreference = $prev
    }
    if (Test-PipWorks $py) {
        Write-Host "  [OK] pip bootstrapped via ensurepip" -ForegroundColor Green
        return $true
    }

    Write-Host "  [..] ensurepip unavailable — fetching get-pip.py..." -ForegroundColor Yellow
    $getPip = Join-Path $env:TEMP "rapp-get-pip.py"
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing -TimeoutSec 120
        & $py $getPip 2>&1 | ForEach-Object { Write-Host "$_" }
    } catch {
    } finally {
        $ErrorActionPreference = $prev
        Remove-Item $getPip -Force -ErrorAction SilentlyContinue
    }
    if (Test-PipWorks $py) {
        Write-Host "  [OK] pip bootstrapped via get-pip.py" -ForegroundColor Green
        return $true
    }

    Write-Host "  [X] Python at '$py' has no pip and it could not be bootstrapped." -ForegroundColor Red
    Write-Host "      Fix it manually, then re-run this installer:" -ForegroundColor Yellow
    Write-Host "        `"$py`" -m ensurepip --upgrade --default-pip" -ForegroundColor Cyan
    Write-Host "      Or reinstall Python from https://python.org with 'pip' checked." -ForegroundColor Yellow
    return $false
}

function Setup-Venv {
    # Create ~/.brainstem/venv so dependencies are isolated from system/user Python
    # and the launcher always resolves the SAME interpreter that install used
    # (issue #29). Idempotent: a healthy existing venv is reused; a broken one is
    # recreated. Mirrors install.sh's setup_venv.
    $venvPy = Get-VenvPython
    if (Test-Path $venvPy) {
        $prev = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & $venvPy -c "import sys" 2>&1 | Out-Null
        $ok = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $prev
        if ($ok) {
            Write-Host "  [OK] Virtual environment OK" -ForegroundColor Green
            return
        }
        Write-Host "  [..] Virtual environment broken — recreating..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force $VENV_DIR -ErrorAction SilentlyContinue
    }

    $sysPy = Resolve-PythonExe
    Write-Host "  Creating virtual environment..."
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $sysPy -m venv $VENV_DIR 2>&1 | Out-Null
    if (-not (Test-Path (Get-VenvPython))) {
        # Some minimal Python installs need ensurepip primed before venv works.
        & $sysPy -m ensurepip --upgrade 2>&1 | Out-Null
        & $sysPy -m venv $VENV_DIR 2>&1 | Out-Null
    }
    $ErrorActionPreference = $prev

    if (-not (Test-Path (Get-VenvPython))) {
        Write-Host "  [X] Failed to create virtual environment at $VENV_DIR" -ForegroundColor Red
        throw "venv creation failed"
    }

    # Upgrade pip inside the venv (best-effort; venv already ships pip).
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & (Get-VenvPython) -m pip install --upgrade pip 2>&1 | Out-Null
    $ErrorActionPreference = $prev
    Write-Host "  [OK] Virtual environment ready" -ForegroundColor Green
}

function Ensure-Git {
    # winget + Git: Check-Prerequisites runs this first; a pinned install runs it before
    # anything else on a machine without git, because checking the pin needs git.

    # winget (ships with Windows 11)
    try {
        winget --version 2>&1 | Out-Null
    } catch {
        Write-Host "  [X] winget not found — this installer requires Windows 10 1709+ or Windows 11" -ForegroundColor Red
        throw "winget not found"
    }

    # Git
    $gitOk = $false
    try {
        $gitVersion = git --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] $gitVersion" -ForegroundColor Green
            $gitOk = $true
        }
    } catch {}
    if (-not $gitOk) {
        Install-WithWinget "Git.Git" "Git"
        try {
            git --version 2>&1 | Out-Null
            Write-Host "  [OK] Git installed" -ForegroundColor Green
        } catch {
            Write-Host "  [X] Git install failed — install manually from https://git-scm.com" -ForegroundColor Red
            throw "Git install failed"
        }
    }
}

function Check-Prerequisites {
    Write-Host "Checking prerequisites..."

    # winget and Git
    Ensure-Git

    # Python 3.11+
    $pythonOk = $false
    $pythonCmd = $null

    # Try multiple python command names (python3 first on some systems, then python)
    foreach ($cmd in @("python3", "python")) {
        try {
            $out = & $cmd --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $out -match "Python 3\.(\d+)") {
                $minor = [int]$Matches[1]
                if ($minor -ge 11) {
                    Write-Host "  [OK] $out" -ForegroundColor Green
                    $pythonOk = $true
                    $pythonCmd = $cmd
                    break
                }
            }
        } catch {}
    }

    if (-not $pythonOk) {
        # Disable Windows App Execution Aliases that shadow real python
        # These stubs print "Python was not found" and prevent detection
        $aliasDir = "$env:LOCALAPPDATA\Microsoft\WindowsApps"
        foreach ($stub in @("python.exe", "python3.exe")) {
            $stubPath = Join-Path $aliasDir $stub
            if (Test-Path $stubPath) {
                try {
                    $target = (Get-Item $stubPath).Target
                    if (-not $target) {
                        # It's an App Execution Alias stub — rename it out of the way
                        Rename-Item $stubPath "$stub.disabled" -ErrorAction SilentlyContinue
                        Write-Host "  [..] Disabled Windows Store python stub" -ForegroundColor Yellow
                    }
                } catch {}
            }
        }

        Install-WithWinget "Python.Python.3.11" "Python 3.11"

        # winget installs to a known path — add it explicitly
        $pyBase = "$env:LOCALAPPDATA\Programs\Python\Python311"
        if (Test-Path $pyBase) {
            $env:Path = "$pyBase;$pyBase\Scripts;$env:Path"
        }
        # Also refresh from registry
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

        # Verify the REAL python is now reachable
        $pythonOk = $false
        foreach ($cmd in @("python3", "python")) {
            try {
                $out = & $cmd --version 2>&1
                if ($LASTEXITCODE -eq 0 -and $out -match "Python 3\.(\d+)") {
                    Write-Host "  [OK] $out installed" -ForegroundColor Green
                    $pythonOk = $true
                    $pythonCmd = $cmd
                    break
                }
            } catch {}
        }

        # Last resort: try the known install path directly
        if (-not $pythonOk) {
            $directPy = "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
            if (Test-Path $directPy) {
                $out = & $directPy --version 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "  [OK] $out installed (direct path)" -ForegroundColor Green
                    $pythonOk = $true
                    $pythonCmd = $directPy
                }
            }
        }

        if (-not $pythonOk) {
            Write-Host "  [X] Python install failed — install from https://python.org" -ForegroundColor Red
            Write-Host "      Make sure to check 'Add Python to PATH' during install" -ForegroundColor Yellow
            throw "Python 3.11+ install failed"
        }
    }

    # Store the working python command for later use
    $script:PythonExe = $pythonCmd

    # GitHub CLI (optional but recommended)
    try {
        gh --version 2>&1 | Out-Null
        Write-Host "  [OK] GitHub CLI installed" -ForegroundColor Green
    } catch {
        Write-Host "  [..] Installing GitHub CLI..." -ForegroundColor Yellow
        Install-WithWinget "GitHub.cli" "GitHub CLI"
        try {
            gh --version 2>&1 | Out-Null
            Write-Host "  [OK] GitHub CLI installed" -ForegroundColor Green
        } catch {
            Write-Host "  [!] GitHub CLI not installed (optional — you can authenticate later)" -ForegroundColor Yellow
        }
    }
}

# ── soul refresh on upgrade (issue #40) ──────────────────────────────────────────
# Normalized SHA-256 of a soul.md, computed IDENTICALLY to rapp_brainstem/tests/soul_hash.py
# so the shipped soul_defaults.sha256 manifest works for both installers. Normalize:
# strip a UTF-8 BOM, CRLF->LF, strip trailing space/tab per line, exactly one trailing
# newline; then Get-FileHash a UTF-8 (no BOM) temp copy. Returns lowercase hex, or $null
# if the file cannot be read/decoded (the caller then preserves the soul untouched).
function Get-NormalizedSoulHash {
    param([string]$Path)
    try {
        # ReadAllText(UTF8) auto-detects and strips a UTF-8 BOM, matching soul_hash.py.
        $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    } catch { return $null }
    $text = $text.Replace("`r`n", "`n").Replace("`r", "`n")
    $lines = $text.Split([char]10)
    for ($i = 0; $i -lt $lines.Length; $i++) {
        $lines[$i] = $lines[$i].TrimEnd([char]32, [char]9)
    }
    $text = [string]::Join([string][char]10, $lines).TrimEnd([char]10) + [string][char]10
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($tmp, $text, (New-Object System.Text.UTF8Encoding($false)))
        return (Get-FileHash -Path $tmp -Algorithm SHA256).Hash.ToLower()
    } catch {
        return $null
    } finally {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
}

# True if $Hash is the first token of some non-comment line in the manifest.
function Test-SoulHashInManifest {
    param([string]$Hash, [string]$ManifestPath)
    if (-not $Hash) { return $false }
    if (-not (Test-Path $ManifestPath)) { return $false }
    foreach ($line in [System.IO.File]::ReadAllLines($ManifestPath)) {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#")) { continue }
        if (($trimmed -split '\s+')[0].ToLower() -eq $Hash.ToLower()) { return $true }
    }
    return $false
}

function Test-PinReleaseForm {
    # A pin names a release in one of the tag forms we ship: a bare 0.6.9, the documented
    # v0.6.9, or the release tag itself, brainstem-v0.6.9. Nothing else is a version: not
    # a branch, HEAD, a commit or a path. Case-sensitive, like the tags (and install.sh).
    param([string]$Pin)
    return ($Pin -cmatch '^(brainstem-v|v)?[0-9]+\.[0-9]+\.[0-9]+\z')
}

function Get-PinBareVersion {
    # 0.6.9, v0.6.9 and brainstem-v0.6.9 all name release 0.6.9.
    param([string]$Pin)
    return (($Pin -creplace '^brainstem-', '') -creplace '^v', '')
}

function Resolve-PinRelease {
    # Resolve a pin against the release tags on the remote, before anything on this
    # machine changes. Only refs/tags/ count. Returns @{ Tag; Commit } (the commit that
    # tag names), or $null after saying why the pin names no release.
    param([string]$Pin, [string]$RepoUrl)
    if (-not (Test-PinReleaseForm $Pin)) {
        Write-Host "  [X] '$Pin' is not a release version. Use X.Y.Z, vX.Y.Z or brainstem-vX.Y.Z, e.g. --version 0.6.9" -ForegroundColor Red
        return $null
    }
    $prev = $ErrorActionPreference
    $prevPrompt = $env:GIT_TERMINAL_PROMPT
    $ErrorActionPreference = 'Continue'
    $env:GIT_TERMINAL_PROMPT = '0'
    try {
        $lines = @(git ls-remote --tags $RepoUrl 2>$null)
        $ok = ($LASTEXITCODE -eq 0)
    } finally {
        $env:GIT_TERMINAL_PROMPT = $prevPrompt
        $ErrorActionPreference = $prev
    }
    if (-not $ok) {
        Write-Host "  [X] Could not read the release tags from $RepoUrl to check $Pin" -ForegroundColor Red
        return $null
    }
    $refs = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([System.StringComparer]::Ordinal)
    foreach ($line in $lines) {
        $parts = "$line".Split([char]9)
        if (($parts.Count -eq 2) -and (-not $refs.ContainsKey($parts[1]))) { $refs[$parts[1]] = $parts[0] }
    }
    $bare = Get-PinBareVersion $Pin
    foreach ($cand in @($Pin, "brainstem-v$bare", "v$bare")) {
        # An annotated tag's peeled line (^{}) names its commit; a lightweight tag's own line does.
        foreach ($ref in @("refs/tags/$cand^{}", "refs/tags/$cand")) {
            if ($refs.ContainsKey($ref)) { return @{ Tag = $cand; Commit = $refs[$ref] } }
        }
    }
    Write-Host "  [X] Version $Pin not found. Available versions:" -ForegroundColor Red
    @($refs.Keys) | Where-Object { $_ -cmatch '^refs/tags/(brainstem-)?v[0-9][^^]*\z' } |
        ForEach-Object { $_.Substring(10) } |
        Sort-Object { try { [version](Get-PinBareVersion $_) } catch { [version]'0.0' } }, { $_ } |
        ForEach-Object { Write-Host "    $_" }
    return $null
}

function Get-PinCommit {
    # Make sure the clone (the current directory) has the resolved release commit,
    # fetching the release tag from the repo when it does not. Returns $true when it is there.
    param([string]$Tag, [string]$Commit, [string]$RepoUrl)
    $prev = $ErrorActionPreference
    $prevPrompt = $env:GIT_TERMINAL_PROMPT
    $ErrorActionPreference = 'Continue'
    $env:GIT_TERMINAL_PROMPT = '0'
    try {
        $have = git rev-parse --verify --quiet "$Commit^{commit}" 2>$null
        if ("$have" -ne $Commit) {
            git fetch --quiet $RepoUrl "+refs/tags/$($Tag):refs/tags/$($Tag)" 2>&1 | Out-Null
            $have = git rev-parse --verify --quiet "$Commit^{commit}" 2>$null
        }
        return ("$have" -eq $Commit)
    } finally {
        $env:GIT_TERMINAL_PROMPT = $prevPrompt
        $ErrorActionPreference = $prev
    }
}

function Test-AtPinnedCommit {
    # True when the checkout already is the pinned commit, detached (so no later pull
    # can move it), with no local edits to the kernel. Assumes the current directory
    # is the repo.
    param([string]$Commit)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $head = git rev-parse --verify --quiet HEAD 2>$null
        if ((-not $Commit) -or ("$head" -ne $Commit)) { return $false }
        git symbolic-ref --quiet HEAD 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { return $false }
        $dirty = git status --porcelain -- $KERNEL_FILES 2>$null
        return (-not $dirty)
    } finally {
        $ErrorActionPreference = $prev
    }
}

# A pinned switch must not lose a user's file. `git checkout` refuses to overwrite an
# untracked file at a path the release tracks, silently overwrites an ignored one, and
# the agent restore skips names the release ships. So before the switch, every file on
# disk at a path the release adds (relative to HEAD) moves into the backup; after the
# switch it is kept beside the release's copy as <path>.bak-<date> (the soul refresh's
# naming), and if the switch does not happen it goes back where it was. Mirrors
# install.sh's pin_blockers / pin_set_aside / pin_put_back / pin_keep_beside.
function Get-PinBlockers {
    # The paths the release commit adds relative to HEAD (current directory = the clone),
    # or $null if git cannot say. A path git has to quote (non-ASCII) is returned quoted;
    # the caller refuses to switch rather than guess at it.
    param([string]$Commit)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $paths = @(git diff --no-renames --name-only --diff-filter=A HEAD $Commit 2>$null)
        if ($LASTEXITCODE -ne 0) { return $null }
        return ,$paths
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Move-PinBlockers {
    # Move each of $Paths that is on disk into $Kept, keeping its relative path. Throws
    # if one cannot be moved. Current directory = the clone.
    param([string[]]$Paths, [string]$Kept)
    foreach ($p in $Paths) {
        if ((-not $p) -or (-not (Test-Path -LiteralPath $p))) { continue }
        $dest = Join-Path $Kept $p
        New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) -ErrorAction Stop | Out-Null
        Move-Item -LiteralPath $p -Destination $dest -Force -ErrorAction Stop
    }
}

function Restore-PinBlockers {
    # Put each file Move-PinBlockers set aside back where it was (the switch did not
    # happen), or with -Beside keep it next to the release's copy as <path>.bak-<date>;
    # a copy identical to the release's is dropped. Returns $false if one could not be
    # restored (it then stays in $Kept). Current directory = the clone.
    param([string[]]$Paths, [string]$Kept, [switch]$Beside, [string]$Tag)
    $ok = $true
    foreach ($p in $Paths) {
        if (-not $p) { continue }
        $saved = Join-Path $Kept $p
        if (-not (Test-Path -LiteralPath $saved)) { continue }
        try {
            if (-not $Beside) {
                Move-Item -LiteralPath $saved -Destination $p -Force -ErrorAction Stop
                continue
            }
            if ((Test-Path -LiteralPath $saved -PathType Leaf) -and (Test-Path -LiteralPath $p -PathType Leaf) -and
                ((Get-FileHash -LiteralPath $saved).Hash -eq (Get-FileHash -LiteralPath $p).Hash)) {
                continue
            }
            $bak = "$p.bak-$(Get-Date -Format 'yyyyMMdd')"
            if (Test-Path -LiteralPath $bak) {
                $n = 1
                while (Test-Path -LiteralPath "$bak-$n") { $n++ }
                $bak = "$bak-$n"
            }
            Move-Item -LiteralPath $saved -Destination $bak -Force -ErrorAction Stop
            Write-Host "  [!] $Tag ships its own $p; yours is kept beside it as $(Join-Path (Get-Location) $bak)" -ForegroundColor Yellow
        } catch {
            Write-Host "  [!] Could not put back $p; it is in $saved" -ForegroundColor Yellow
            $ok = $false
        }
    }
    return $ok
}

function Sync-PinnedKernel {
    # A pinned install must run the release's kernel bytes exactly. A checkout does not
    # guarantee that: files the switch did not change keep whatever bytes an earlier
    # clone wrote, and core.autocrlf=true (the Git for Windows default) writes CRLF line
    # endings. Rewrite any kernel file whose raw bytes differ from the release's blob
    # straight from the release commit with line-ending conversion off, then report the
    # result. Assumes the current directory is the repo.
    param([string]$Commit, [string]$Tag)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $drift = @()
    try {
        foreach ($f in $KERNEL_FILES) {
            $want = git rev-parse --verify --quiet "$($Commit):$f" 2>$null
            if (-not $want) { continue }
            $have = git hash-object --no-filters -- $f 2>$null
            if ("$have" -ne "$want") {
                Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue
                git -c core.autocrlf=false -c core.eol=lf checkout --quiet $Commit -- $f 2>&1 | Out-Null
                $have = git hash-object --no-filters -- $f 2>$null
            }
            if ("$have" -ne "$want") { $drift += $f }
        }
    } finally {
        $ErrorActionPreference = $prev
    }
    if ($drift.Count -gt 0) {
        Write-Host "  [!] Kernel files still differ from ${Tag}: $($drift -join ', ')" -ForegroundColor Yellow
    } else {
        Write-Host "  [OK] Kernel matches $Tag byte-for-byte" -ForegroundColor Green
    }
}

function Save-UserState {
    # Before a re-clone over a broken install: copy the user state ($USER_STATE_FILES,
    # $USER_STATE_DIRS) and every agent from rapp_brainstem\ ($From) into $To.
    param([string]$From, [string]$To)
    New-Item -ItemType Directory -Force -Path "$To\agents" | Out-Null
    foreach ($f in $USER_STATE_FILES) {
        if (Test-Path -LiteralPath "$From\$f" -PathType Leaf) { Copy-Item -LiteralPath "$From\$f" -Destination "$To\$f" -Force -ErrorAction SilentlyContinue }
    }
    foreach ($d in $USER_STATE_DIRS) {
        if (Test-Path -LiteralPath "$From\$d" -PathType Container) { Copy-Item -LiteralPath "$From\$d" -Destination "$To\$d" -Recurse -Force -ErrorAction SilentlyContinue }
    }
    if (Test-Path "$From\agents") { Copy-Item "$From\agents\*.py" "$To\agents\" -Force -ErrorAction SilentlyContinue }
}

function Restore-UserState {
    # After the re-clone: put what Save-UserState kept ($From) over the new rapp_brainstem\
    # ($To). Custom agents come back; basic_agent.py and __init__.py stay the release's.
    param([string]$From, [string]$To)
    foreach ($f in $USER_STATE_FILES) {
        if (Test-Path -LiteralPath "$From\$f" -PathType Leaf) { Copy-Item -LiteralPath "$From\$f" -Destination "$To\$f" -Force -ErrorAction SilentlyContinue }
    }
    foreach ($d in $USER_STATE_DIRS) {
        if ((Test-Path -LiteralPath "$From\$d" -PathType Container) -and (-not (Test-Path -LiteralPath "$To\$d"))) {
            Copy-Item -LiteralPath "$From\$d" -Destination "$To\$d" -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    if (-not (Test-Path "$To\agents")) { New-Item -ItemType Directory -Force -Path "$To\agents" | Out-Null }
    Get-ChildItem "$From\agents\*.py" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -notin @("basic_agent.py", "__init__.py")) {
            Copy-Item $_.FullName "$To\agents\$($_.Name)" -Force -ErrorAction SilentlyContinue
        }
    }
}

function Install-Brainstem {
    Write-Host ""
    Write-Host "Installing RAPP Brainstem..."

    if (-not (Test-Path $BRAINSTEM_HOME)) {
        New-Item -ItemType Directory -Force -Path $BRAINSTEM_HOME | Out-Null
    }

    if (Test-Path "$BRAINSTEM_HOME\src\.git") {
        # Smart update — preserve soul, agents, config
        $LocalVer = "0.0.0"
        $VerFile = "$BRAINSTEM_HOME\src\rapp_brainstem\VERSION"
        if (Test-Path $VerFile) { $LocalVer = (Get-Content $VerFile -Raw).Trim() }
        $NeedSwitch = $true
        if ($PIN_VERSION) {
            $RemoteVer = Get-PinBareVersion $script:PIN_TAG
            # Main resolved the pin against the remote. Bring its commit into this clone
            # before touching anything: if that fails, the install stays exactly as it was.
            Push-Location "$BRAINSTEM_HOME\src"
            $havePin = Get-PinCommit -Tag $script:PIN_TAG -Commit $script:PIN_COMMIT -RepoUrl $REPO_URL
            # Compare commits, not VERSION strings: a checkout whose VERSION matches can
            # still be a different commit (or a branch a later pull would move).
            if ($havePin) { $NeedSwitch = -not (Test-AtPinnedCommit $script:PIN_COMMIT) }
            Pop-Location
            if (-not $havePin) {
                Write-Host "  [X] Could not fetch $($script:PIN_TAG) ($($script:PIN_COMMIT)) from $REPO_URL" -ForegroundColor Red
                throw "could not fetch $($script:PIN_TAG); nothing was changed"
            }
        } else {
            try { $RemoteVer = (Invoke-WebRequest -Uri $REMOTE_VERSION_URL -UseBasicParsing -TimeoutSec 5).Content.Trim() } catch { $RemoteVer = "0.0.0" }
            $NeedSwitch = ($LocalVer -ne $RemoteVer)
        }

        Write-Host "  Local:  v$LocalVer"
        if ($PIN_VERSION) {
            Write-Host "  Target: v$RemoteVer (pinned: $($script:PIN_TAG))"
        } else {
            Write-Host "  Remote: v$RemoteVer"
        }

        if (-not $NeedSwitch) {
            if ($PIN_VERSION) {
                Write-Host "  [OK] Already on v$LocalVer ($($script:PIN_TAG))" -ForegroundColor Green
            } else {
                Write-Host "  [OK] Already up to date (v$LocalVer)" -ForegroundColor Green
            }
        } else {
            if ($PIN_VERSION) {
                Write-Host "  Switching v$LocalVer -> v$RemoteVer..."
            } else {
                Write-Host "  Upgrading v$LocalVer -> v$RemoteVer..."
            }
            $Backup = "$env:TEMP\brainstem-upgrade-$(Get-Random)"
            New-Item -ItemType Directory -Force -Path $Backup | Out-Null

            # Backup user files
            $AgentsDir = "$BRAINSTEM_HOME\src\rapp_brainstem\agents"
            $SoulFile = "$BRAINSTEM_HOME\src\rapp_brainstem\soul.md"
            $EnvFile = "$BRAINSTEM_HOME\src\rapp_brainstem\.env"
            if (Test-Path $SoulFile) { Copy-Item $SoulFile "$Backup\soul.md" }
            if (Test-Path $EnvFile) { Copy-Item $EnvFile "$Backup\.env" }
            if (Test-Path $AgentsDir) { Copy-Item "$AgentsDir\*.py" "$Backup\" -ErrorAction SilentlyContinue }
            Write-Host "  [OK] Backed up soul, agents, config" -ForegroundColor Green

            # Unpinned: pull latest from THIS installer's repo. A prior install may have cloned
            # from a different origin (fork/mirror); repoint origin and hard-reset to it so the
            # upgrade is reliable even across unrelated histories. User files (soul, agents,
            # .env) were backed up above and are restored below; tokens and .brainstem_data are
            # gitignored. A pin needs no origin: it checks out the commit fetched from the repo.
            Push-Location "$BRAINSTEM_HOME\src"
            $prevEAP = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            $Blockers = @()
            $Kept = "$Backup\kept"
            $keptOk = $true
            $switchError = @()
            if ($PIN_VERSION) {
                # Pin/RC-test: switch to the release commit resolved above without forcing:
                # set aside the files the switch would overwrite (Get-PinBlockers), and let
                # git refuse anything else.
                $stashBefore = "$(git rev-parse --verify --quiet refs/stash 2>$null)"
                git stash 2>&1 | Out-Null
                $pullOk = $false
                $Blockers = Get-PinBlockers $script:PIN_COMMIT
                if ($null -eq $Blockers) {
                    $Blockers = @()
                    $switchError = @("could not list the files $($script:PIN_TAG) would overwrite")
                } elseif (@($Blockers | Where-Object { "$_".StartsWith('"') }).Count -gt 0) {
                    $switchError = @("cannot set these aside safely: " + (@($Blockers | Where-Object { "$_".StartsWith('"') }) -join ', '))
                    $Blockers = @()
                } else {
                    try {
                        Move-PinBlockers -Paths $Blockers -Kept $Kept
                        $switchError = @(git checkout --quiet --detach $script:PIN_COMMIT 2>&1 | ForEach-Object { "$_" })
                        $pullOk = ($LASTEXITCODE -eq 0)
                    } catch {
                        $switchError = @("$($_.Exception.Message)")
                    }
                }
                if (-not $pullOk) {
                    # Put the install back as it was: the set-aside files, and the edits the
                    # stash just took.
                    $keptOk = Restore-PinBlockers -Paths $Blockers -Kept $Kept -Tag $script:PIN_TAG
                    if ("$(git rev-parse --verify --quiet refs/stash 2>$null)" -ne $stashBefore) {
                        git stash pop --quiet 2>&1 | Out-Null
                        if ($LASTEXITCODE -ne 0) { Write-Host "  [!] Your uncommitted edits are saved in: git -C `"$BRAINSTEM_HOME\src`" stash list" -ForegroundColor Yellow }
                    }
                }
            } else {
                git remote set-url origin $REPO_URL 2>&1 | Out-Null
                git fetch --quiet origin main 2>&1 | Out-Null
                $pullOk = ($LASTEXITCODE -eq 0)
                if ($pullOk) {
                    git reset --hard --quiet FETCH_HEAD 2>&1 | Out-Null
                    $pullOk = ($LASTEXITCODE -eq 0)
                }
            }
            $ErrorActionPreference = $prevEAP
            Pop-Location
            if ($pullOk) {
                if ($PIN_VERSION) {
                    Write-Host "  [OK] Checked out $($script:PIN_TAG)" -ForegroundColor Green
                } else {
                    Write-Host "  [OK] Framework updated" -ForegroundColor Green
                }
            } elseif ($PIN_VERSION) {
                Write-Host "  [X] Could not check out $($script:PIN_TAG) - keeping existing files (v$LocalVer):" -ForegroundColor Red
                $switchError | ForEach-Object { Write-Host "      $_" }
            } else {
                Write-Host "  [!] Update download failed — keeping existing files (v$LocalVer)" -ForegroundColor Yellow
            }

            # Restore user files.
            # soul.md: refresh it only when the pre-upgrade file was an unmodified
            # historical default (issue #40) — its normalized hash is in the manifest
            # AND the new default differs; then back the old one up to soul.md.bak-<date>.
            # Otherwise (any customization, or anything we cannot hash) preserve it
            # byte-for-byte. Fail-safe: preserve, never clobber.
            if (Test-Path "$Backup\soul.md") {
                $soulRefreshed = $false
                if ($pullOk) {
                    $Manifest = "$BRAINSTEM_HOME\src\rapp_brainstem\tests\soul_defaults.sha256"
                    $OldHash = Get-NormalizedSoulHash "$Backup\soul.md"
                    $NewHash = Get-NormalizedSoulHash $SoulFile
                    if ($OldHash -and $NewHash -and ($OldHash -ne $NewHash) -and (Test-SoulHashInManifest $OldHash $Manifest)) {
                        $Bak = "$BRAINSTEM_HOME\src\rapp_brainstem\soul.md.bak-$(Get-Date -Format 'yyyyMMdd')"
                        # Don't clobber an earlier same-day backup (a second refresh on the same date).
                        if (Test-Path $Bak) {
                            $bn = 1
                            while (Test-Path "$Bak-$bn") { $bn++ }
                            $Bak = "$Bak-$bn"
                        }
                        Copy-Item "$Backup\soul.md" $Bak
                        Write-Host "  [OK] Refreshed default soul (yours was an unmodified default); backup at $Bak" -ForegroundColor Green
                        $soulRefreshed = $true
                    }
                }
                if (-not $soulRefreshed) { Copy-Item "$Backup\soul.md" $SoulFile -Force }
            }
            if (Test-Path "$Backup\.env") { Copy-Item "$Backup\.env" $EnvFile -Force }
            # Only restore genuinely user-added agents. Compute the set the repo now
            # ships from the fresh checkout and skip-restore anything in it — otherwise
            # bundled agents (context_memory, manage_memory, hacker_news) get reverted
            # to the backed-up copies on every upgrade (issue #2).
            $Shipped = @()
            if (Test-Path $AgentsDir) {
                $Shipped = @(Get-ChildItem "$AgentsDir\*.py" -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
            }
            Get-ChildItem "$Backup\*.py" -ErrorAction SilentlyContinue | ForEach-Object {
                if (($_.Name -notin @("basic_agent.py", "__init__.py")) -and ($_.Name -notin $Shipped)) {
                    Copy-Item $_.FullName "$AgentsDir\$($_.Name)" -Force
                }
            }
            # A pinned switch that landed keeps each file it set aside beside the release's copy.
            if ($PIN_VERSION -and $pullOk) {
                Push-Location "$BRAINSTEM_HOME\src"
                $keptOk = Restore-PinBlockers -Paths $Blockers -Kept $Kept -Beside -Tag $script:PIN_TAG
                Pop-Location
            }
            if ($keptOk) {
                Remove-Item -Recurse -Force $Backup -ErrorAction SilentlyContinue
            } else {
                Write-Host "  [!] Some of your files could not be put back; they are in $Kept" -ForegroundColor Yellow
            }
            # Report the version actually on disk after the pull, not the remote string —
            # if the pull failed the banner must not claim a successful upgrade.
            $NewVer = $LocalVer
            if (Test-Path $VerFile) { $NewVer = (Get-Content $VerFile -Raw).Trim() }
            if ($pullOk -and $PIN_VERSION) {
                Write-Host "  [OK] Pinned: v$LocalVer -> v$NewVer ($($script:PIN_TAG))" -ForegroundColor Green
            } elseif ($pullOk -and $NewVer -ne $LocalVer) {
                Write-Host "  [OK] Upgrade complete: v$LocalVer -> v$NewVer" -ForegroundColor Green
            } elseif ($pullOk) {
                Write-Host "  [OK] Already at the latest framework (v$NewVer)" -ForegroundColor Green
            }
            # A pin that did not land must not go on to launch whatever was there before.
            if ($PIN_VERSION -and -not $pullOk) { throw "could not check out $($script:PIN_TAG)" }
        }
    } else {
        # A broken prior install (src present but .git gone) may still hold the user's
        # soul, .env, tokens, custom agents, and memories - none of which are in git.
        # Preserve them ($USER_STATE_FILES, $USER_STATE_DIRS) before wiping so a re-run
        # can't silently destroy the user's work (issue #21). The common case (no
        # existing src) skips all of this.
        $FreshBackup = $null
        $PinFailure = $null
        $srcRapp = "$BRAINSTEM_HOME\src\rapp_brainstem"
        if (Test-Path $srcRapp) {
            $FreshBackup = "$env:TEMP\brainstem-fresh-$(Get-Random)"
            Save-UserState -From $srcRapp -To $FreshBackup
        }

        if (Test-Path "$BRAINSTEM_HOME\src") {
            Remove-Item -Recurse -Force "$BRAINSTEM_HOME\src" -ErrorAction SilentlyContinue
        }
        Write-Host "  Cloning repository..."
        git clone --quiet $REPO_URL "$BRAINSTEM_HOME\src" 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [X] Failed to clone repository" -ForegroundColor Red
            throw "git clone failed"
        }

        if ($PIN_VERSION) {
            # Pin/RC-test: check out the release commit Main resolved, detached.
            Push-Location "$BRAINSTEM_HOME\src"
            if (Get-PinCommit -Tag $script:PIN_TAG -Commit $script:PIN_COMMIT -RepoUrl $REPO_URL) {
                $prevEAP = $ErrorActionPreference
                $ErrorActionPreference = 'Continue'
                git checkout --quiet --detach $script:PIN_COMMIT 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0) { $PinFailure = "could not check out $($script:PIN_TAG)" }
                $ErrorActionPreference = $prevEAP
            } else {
                Write-Host "  [X] Could not fetch $($script:PIN_TAG) ($($script:PIN_COMMIT)) from $REPO_URL" -ForegroundColor Red
                $PinFailure = "could not fetch $($script:PIN_TAG)"
            }
            Pop-Location
            if (-not $PinFailure) { Write-Host "  [OK] Checked out $($script:PIN_TAG)" -ForegroundColor Green }
        }

        # Restore any preserved user files over the fresh checkout, also when the pin
        # did not land, so they are never stranded in the temporary backup.
        if ($FreshBackup) {
            Restore-UserState -From $FreshBackup -To $srcRapp
            Remove-Item -Recurse -Force $FreshBackup -ErrorAction SilentlyContinue
            Write-Host "  [OK] Preserved your soul, agents, memories, tokens, and config" -ForegroundColor Green
        }
        if ($PinFailure) { throw $PinFailure }
    }
    if ($PIN_VERSION) {
        Push-Location "$BRAINSTEM_HOME\src"
        Sync-PinnedKernel -Commit $script:PIN_COMMIT -Tag $script:PIN_TAG
        Pop-Location
    }
    Write-Host "  [OK] Source code ready" -ForegroundColor Green
}

function Run-PipInstall {
    $reqFile = "$BRAINSTEM_HOME\src\rapp_brainstem\requirements.txt"
    # Install into the venv (issue #29). The venv created by Setup-Venv already ships
    # pip; only the rare system-python fallback (no venv) needs pip bootstrapping.
    $py = Resolve-RunPython
    if (-not (Test-PipWorks $py)) {
        if (-not (Ensure-Pip)) { return }
        $py = Resolve-RunPython
    }
    # Use the call operator, NOT Start-Process (same reasoning as Check-PythonDeps):
    # the call operator quotes a $reqFile path containing spaces correctly, and it
    # needs no console attachment — Start-Process -NoNewWindow -Wait can block
    # forever in consoleless sessions (CI, some terminal hosts). Drop
    # ErrorActionPreference to Continue locally so pip's stderr progress lines are
    # not promoted to a terminating NativeCommandError under the script's global
    # $ErrorActionPreference = 'Stop'.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $py -m pip install -r $reqFile 2>&1 | ForEach-Object { "$_" }
        # `--user` is only valid (and only needed) on the system-python fallback; it
        # errors inside a venv, so skip it when installing into the venv.
        if ($LASTEXITCODE -ne 0 -and $py -ne (Get-VenvPython)) {
            & $py -m pip install -r $reqFile --user 2>&1 | ForEach-Object { "$_" }
        }
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Check-PythonDeps {
    $py = Resolve-RunPython
    # Use the call operator, NOT Start-Process -ArgumentList. Start-Process joins array
    # arguments with spaces but does not re-quote an element that itself contains spaces,
    # so "-c", "import flask, flask_cors, ..." reached python as the tokens
    # "-c import flask, flask_cors, ..." — python's -c got only "import" -> SyntaxError.
    # The call operator quotes arguments correctly. Drop ErrorActionPreference to Continue
    # locally so python's stderr (e.g. when a module is missing) is not promoted to a
    # terminating NativeCommandError under the script's global $ErrorActionPreference='Stop'.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $py -c "import flask, flask_cors, requests, dotenv" 2>&1 | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Setup-Dependencies {
    Write-Host ""
    Write-Host "Installing dependencies..."
    Push-Location "$BRAINSTEM_HOME\src\rapp_brainstem"
    Run-PipInstall
    $depsOk = Check-PythonDeps
    if (-not $depsOk) {
        # v0.6.2 accidentally self-healed transient pip failures via the second
        # Run-PipInstall in Launch-Brainstem. Keep one deliberate retry here so
        # a PyPI/DNS blip doesn't hard-abort a fresh install.
        Write-Host "  [..] Dependency check failed — retrying pip install once..." -ForegroundColor Yellow
        Run-PipInstall
        $depsOk = Check-PythonDeps
    }
    Pop-Location
    if (-not $depsOk) {
        # Never print [OK] and continue toward a server that will die at
        # `import requests` behind a dead browser tab — stop here, honestly,
        # with the guidance Ensure-Pip/pip printed above.
        throw "Python dependencies failed to install (see messages above)"
    }
    Write-Host "  [OK] Dependencies installed" -ForegroundColor Green
}

function Ensure-Dependencies {
    # Quick import check — only run pip when something is actually missing (mirrors
    # install.sh's ensure_deps; keeps the fast path from hitting PyPI every launch).
    Push-Location "$BRAINSTEM_HOME\src\rapp_brainstem"
    if (Check-PythonDeps) {
        Pop-Location
        Write-Host "  [OK] Dependencies verified" -ForegroundColor Green
        return
    }
    Write-Host "  [..] Missing dependencies — installing..." -ForegroundColor Yellow
    Run-PipInstall
    $ok = Check-PythonDeps
    Pop-Location
    if (-not $ok) {
        throw "Python dependencies are missing and could not be installed (see messages above)"
    }
    Write-Host "  [OK] Dependencies installed" -ForegroundColor Green
}

function Install-CLI {
    Write-Host ""
    Write-Host "Installing CLI..."

    if (-not (Test-Path $BRAINSTEM_BIN)) {
        New-Item -ItemType Directory -Force -Path $BRAINSTEM_BIN | Out-Null
    }

    # Wrappers launch the venv interpreter (issue #29) so `brainstem` always runs the
    # same Python that install set up; if the venv is ever missing they fall back to
    # the system Python captured here. Quote every interpreter path — the direct-path
    # fallback (…\First Last\AppData\…\python.exe) contains spaces.
    $venvPy = Get-VenvPython
    $sysPy = Resolve-PythonExe
    # Batch wrapper (works in cmd.exe and PowerShell). A goto (not an if/else block)
    # avoids cmd.exe mis-parsing a path that happens to contain a parenthesis.
    $cmdContent = @"
@echo off
cd /d "$BRAINSTEM_HOME\src\rapp_brainstem"
if exist "$venvPy" goto RAPP_VENV
"$sysPy" brainstem.py %*
goto :eof
:RAPP_VENV
"$venvPy" brainstem.py %*
"@
    Set-Content -Path "$BRAINSTEM_BIN\brainstem.cmd" -Value $cmdContent

    # PowerShell wrapper
    $psContent = @"
Set-Location "$BRAINSTEM_HOME\src\rapp_brainstem"
if (Test-Path "$venvPy") { & "$venvPy" brainstem.py @args } else { & "$sysPy" brainstem.py @args }
"@
    Set-Content -Path "$BRAINSTEM_BIN\brainstem.ps1" -Value $psContent

    # Add to PATH if not already there
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$BRAINSTEM_BIN*") {
        [Environment]::SetEnvironmentVariable("Path", "$BRAINSTEM_BIN;$userPath", "User")
        $env:Path = "$BRAINSTEM_BIN;$env:Path"
        Write-Host "  Added to PATH" -ForegroundColor Green
    }

    Write-Host "  [OK] CLI installed" -ForegroundColor Green
}

function Create-Env {
    $envFile = "$BRAINSTEM_HOME\src\rapp_brainstem\.env"
    $exampleFile = "$BRAINSTEM_HOME\src\rapp_brainstem\.env.example"
    if (-not (Test-Path $envFile) -and (Test-Path $exampleFile)) {
        Copy-Item $exampleFile $envFile
    }
}

function Launch-Brainstem {
    # Refresh from this installer's repo before launching (no-op if already current).
    # Skip when a version is pinned — pulling main would move off the pinned tag.
    if ((-not $PIN_VERSION) -and (Test-Path "$BRAINSTEM_HOME\src\.git")) {
        Push-Location "$BRAINSTEM_HOME\src"
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        git remote set-url origin $REPO_URL 2>&1 | Out-Null
        git pull --quiet origin main 2>&1 | Out-Null
        $ErrorActionPreference = $prevEAP
        Pop-Location
    }

    # Dependencies BEFORE auth: if they cannot be installed, fail now — not after
    # walking the user through a GitHub device-code authorization they can't use.
    Push-Location "$BRAINSTEM_HOME\src\rapp_brainstem"
    if (-not (Check-PythonDeps)) {
        Write-Host "  [..] Installing missing dependencies..." -ForegroundColor Yellow
        Run-PipInstall
        if (-not (Check-PythonDeps)) {
            Pop-Location
            # Launching anyway would crash at `import requests` and strand the user
            # on a browser tab pointing at a server that never bound port 7071.
            throw "Python dependencies are missing and could not be installed (see messages above)"
        }
    }
    Pop-Location

    $tokenFile = "$BRAINSTEM_HOME\src\rapp_brainstem\.copilot_token"
    $clientId = "Iv1.b507a08c87ecfe98"

    # Check if already authenticated
    $needsAuth = $true
    if (Test-Path $tokenFile) {
        try {
            $tokenData = Get-Content $tokenFile -Raw | ConvertFrom-Json
            $savedToken = $tokenData.access_token
            if ($savedToken) {
                $authPrefix = if ($savedToken.StartsWith("ghu_")) { "token" } else { "Bearer" }
                $headers = @{
                    "Authorization" = "$authPrefix $savedToken"
                    "Accept" = "application/json"
                    "Editor-Version" = "vscode/1.95.0"
                    "Editor-Plugin-Version" = "copilot/1.0.0"
                }
                try {
                    $checkResp = Invoke-WebRequest -Uri "https://api.github.com/copilot_internal/v2/token" -Headers $headers -UseBasicParsing -TimeoutSec 10 -ErrorAction SilentlyContinue
                    if ($checkResp.StatusCode -eq 200) {
                        Write-Host "  [OK] Already authenticated with GitHub Copilot" -ForegroundColor Green
                        $needsAuth = $false
                    }
                } catch {
                    Write-Host "  [..] Saved token expired — re-authenticating..." -ForegroundColor Yellow
                    Remove-Item $tokenFile -Force -ErrorAction SilentlyContinue
                }
            }
        } catch {
            Remove-Item $tokenFile -Force -ErrorAction SilentlyContinue
        }
    }

    if ($needsAuth) {
        Write-Host ""
        Write-Host "  Authenticating with GitHub Copilot..." -ForegroundColor Cyan
        Write-Host ""

        try {
            $deviceResp = Invoke-RestMethod -Uri "https://github.com/login/device/code" -Method Post -ContentType "application/x-www-form-urlencoded" -Body "client_id=$clientId" -Headers @{"Accept"="application/json"} -TimeoutSec 10

            $userCode = $deviceResp.user_code
            $deviceCode = $deviceResp.device_code
            $interval = if ($deviceResp.interval) { $deviceResp.interval } else { 5 }
            $verifyUri = $deviceResp.verification_uri

            if (-not $userCode -or -not $deviceCode) {
                Write-Host "  [!] Could not start auth — sign in at http://localhost:7071/login" -ForegroundColor Yellow
            } else {
                Write-Host "  ┌─────────────────────────────────────────┐"
                Write-Host "  │  Your code: " -NoNewline; Write-Host $userCode -ForegroundColor Cyan -NoNewline; Write-Host "                  │"
                Write-Host "  └─────────────────────────────────────────┘"
                Write-Host ""
                Write-Host "  Opening browser to authorize..."

                Start-Process $verifyUri
                Write-Host "  Waiting for authorization..."
                Write-Host ""

                for ($i = 0; $i -lt 60; $i++) {
                    Start-Sleep -Seconds $interval
                    try {
                        $pollResp = Invoke-RestMethod -Uri "https://github.com/login/oauth/access_token" -Method Post -ContentType "application/x-www-form-urlencoded" -Body "client_id=$clientId&device_code=$deviceCode&grant_type=urn:ietf:params:oauth:grant-type:device_code" -Headers @{"Accept"="application/json"} -TimeoutSec 10

                        if ($pollResp.access_token) {
                            $tokenJson = @{ access_token = $pollResp.access_token }
                            if ($pollResp.refresh_token) { $tokenJson.refresh_token = $pollResp.refresh_token }
                            $tokenJson | ConvertTo-Json | Set-Content $tokenFile

                            # Validate Copilot access
                            $authPrefix = if ($pollResp.access_token.StartsWith("ghu_")) { "token" } else { "Bearer" }
                            $headers = @{
                                "Authorization" = "$authPrefix $($pollResp.access_token)"
                                "Accept" = "application/json"
                                "Editor-Version" = "vscode/1.95.0"
                                "Editor-Plugin-Version" = "copilot/1.0.0"
                            }
                            try {
                                $copilotCheck = Invoke-WebRequest -Uri "https://api.github.com/copilot_internal/v2/token" -Headers $headers -UseBasicParsing -TimeoutSec 10 -ErrorAction SilentlyContinue
                                if ($copilotCheck.StatusCode -eq 200) {
                                    Write-Host "  [OK] Authenticated — Copilot access confirmed" -ForegroundColor Green
                                }
                            } catch {
                                $statusCode = $_.Exception.Response.StatusCode.value__
                                if ($statusCode -eq 403) {
                                    Write-Host ""
                                    Write-Host "  [X] This GitHub account does NOT have Copilot access." -ForegroundColor Red
                                    Write-Host ""
                                    Write-Host "  Either:"
                                    Write-Host "    1. Sign up for Copilot: " -NoNewline; Write-Host "https://github.com/github-copilot/signup" -ForegroundColor Cyan
                                    Write-Host "    2. Re-run this installer and sign in with a different account"
                                    Write-Host ""
                                    Remove-Item $tokenFile -Force -ErrorAction SilentlyContinue
                                } else {
                                    Write-Host "  [OK] Authenticated with GitHub" -ForegroundColor Green
                                }
                            }
                            break
                        }

                        $error_code = $pollResp.error
                        if ($error_code -eq "expired_token") {
                            Write-Host "  [!] Auth timed out — sign in at http://localhost:7071/login" -ForegroundColor Yellow
                            break
                        }
                        if ($error_code -ne "authorization_pending" -and $error_code -ne "slow_down" -and $error_code) {
                            Write-Host "  [!] Auth error: $error_code" -ForegroundColor Yellow
                            break
                        }
                    } catch {}
                }
            }
        } catch {
            Write-Host "  [!] Could not start auth — sign in at http://localhost:7071/login" -ForegroundColor Yellow
        }
    }

    # Launch the server
    Write-Host ""
    Write-Host "  Starting RAPP Brainstem..." -ForegroundColor Cyan
    Write-Host ""

    Push-Location "$BRAINSTEM_HOME\src\rapp_brainstem"

    # Free port 7071 before launching — an upgrade must not leave the OLD server
    # running, or the health poll below would pass against it and report a false
    # success while the new code never actually binds the port. Guarded for the
    # absence of Get-NetTCPConnection (older/Server SKUs).
    try {
        $listeners = Get-NetTCPConnection -LocalPort 7071 -State Listen -ErrorAction SilentlyContinue
        if ($listeners) {
            $ownerPids = @($listeners | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
            foreach ($ownerPid in $ownerPids) {
                if ($ownerPid -and $ownerPid -ne 0) {
                    Write-Host "  [!] Stopping existing server (PID $ownerPid)..." -ForegroundColor Yellow
                    Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
                }
            }
            Start-Sleep -Seconds 1
        }
    } catch {}

    # Open the browser once the server actually answers (#14) — a fixed delay
    # races cold startups and lands the user on a dead-port error page. Poll
    # /health, then open; after 60s open anyway so the user still gets the tab.
    Start-Job -ScriptBlock {
        for ($i = 0; $i -lt 60; $i++) {
            try {
                Invoke-WebRequest -Uri "http://localhost:7071/health" -UseBasicParsing -TimeoutSec 1 | Out-Null
                break
            } catch {
                Start-Sleep -Seconds 1
            }
        }
        Start-Process "http://localhost:7071"
    } | Out-Null

    $py = Resolve-RunPython
    & $py brainstem.py
}

function Main {
    Print-Banner

    # A malformed pin stops here, before anything on the machine changes.
    if ($PIN_REQUEST.Error) { throw $PIN_REQUEST.Error }

    if ($PIN_VERSION) {
        Write-Host "  Pinning to version: $PIN_VERSION (from $($PIN_REQUEST.Source))" -ForegroundColor Cyan
        # Check the pin against the release tags on the remote before anything on this
        # machine changes: no prerequisite install, backup, stash, wipe or clone yet. The
        # check needs git, so a machine without git gets it first.
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Ensure-Git }
        $release = Resolve-PinRelease -Pin $PIN_VERSION -RepoUrl $REPO_URL
        if (-not $release) { throw "cannot pin $PIN_VERSION (see above); nothing was changed" }
        $script:PIN_TAG = $release.Tag
        $script:PIN_COMMIT = $release.Commit
        Write-Host "  [OK] $PIN_VERSION is release $($script:PIN_TAG) ($($script:PIN_COMMIT.Substring(0, 12)))" -ForegroundColor Green
        Write-Host ""
    }

    # Check if this is an upgrade of an existing install. Skip the fast path when a
    # version is pinned — Install-Brainstem must run to check out the requested tag.
    if ((-not $PIN_VERSION) -and (Test-Path "$BRAINSTEM_HOME\src\.git")) {
        Write-Host "Checking for updates..."
        if (-not (Check-ForUpgrade)) {
            # Already up to date — still re-heal the environment before launching,
            # exactly like install.sh's fast path: verify prerequisites, the venv and
            # deps, rewrite the CLI wrappers, and restore a missing .env (issues #9, #3).
            Check-Prerequisites
            Setup-Venv
            Ensure-Dependencies
            Install-CLI
            Create-Env
            Launch-Brainstem
            return
        }
    }

    Check-Prerequisites
    Install-Brainstem
    # Create the venv before the CLI wrappers (which point at it) and before deps
    # (which install into it) so install and launch share one interpreter (issue #29).
    Setup-Venv
    # CLI wrappers and .env before dependencies: they are cheap, offline-safe and
    # idempotent. If Setup-Dependencies throws, VERSION already matches remote, so
    # a re-run takes the fast path and would otherwise never come back for them.
    Install-CLI
    Create-Env
    Setup-Dependencies

    $installedVersion = ""
    $vf = "$BRAINSTEM_HOME\src\rapp_brainstem\VERSION"
    if (Test-Path $vf) { $installedVersion = (Get-Content $vf -Raw).Trim() }

    Write-Host ""
    Write-Host "===================================================" -ForegroundColor Cyan
    Write-Host "  [OK] RAPP Brainstem v$installedVersion installed!" -ForegroundColor Green
    Write-Host "===================================================" -ForegroundColor Cyan
    Write-Host ""

    Launch-Brainstem
}

# Invoked as `irm … | iex`, a bare `exit`/uncaught throw terminates the USER'S whole
# PowerShell session — the window closes and the error vanishes. Catch here so a
# failure prints an actionable message and control returns to their prompt instead.
try {
    Main
} catch {
    Write-Host ""
    Write-Host "  [X] Install failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "      Nothing was launched. Fix the issue above and re-run the installer." -ForegroundColor Yellow
    Write-Host "      Need help? Open an issue at https://github.com/kody-w/rapp-installer/issues" -ForegroundColor Gray
    Write-Host ""
    # `irm | iex` has no $PSCommandPath — return to the prompt quietly. A file-based
    # run (CI, a saved script) must still report failure through the exit code.
    if ($PSCommandPath) { exit 1 }
}
