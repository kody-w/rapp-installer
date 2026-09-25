# Version-pin tests for install.ps1 (organism gap G23). test_installer.sh runs this
# when PowerShell is available:
#   pwsh -NoProfile -File tests/test_install_pin.ps1 <origin-repo> <work-dir>
# <origin-repo> is a git repository tagged brainstem-v0.0.1 whose main is ahead of the
# tag (test_installer.sh builds it). The pin code is loaded straight out of install.ps1
# (its functions and kernel file list) without running the installer. Prints one
# "PASS <check>" or "FAIL <check>" line per check and exits 1 if any check failed.
param([string]$Origin, [string]$Work)

$ErrorActionPreference = 'Continue'
$script:failures = 0

function Assert-Case {
    param([bool]$Condition, [string]$What)
    if ($Condition) {
        Write-Output "PASS $What"
    } else {
        Write-Output "FAIL $What"
        $script:failures++
    }
}

$installer = Join-Path (Split-Path $PSScriptRoot -Parent) 'install.ps1'
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($installer, [ref]$null, [ref]$parseErrors)
Assert-Case (-not $parseErrors) 'install.ps1 parses'

$definitions = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false)
foreach ($name in @('Get-PinRequest', 'Get-PinBareVersion', 'Resolve-PinnedTag', 'Test-AtPinnedCommit', 'Sync-PinnedKernel')) {
    $definition = $definitions | Where-Object { $_.Name -eq $name } | Select-Object -First 1
    Assert-Case ($null -ne $definition) "defines $name"
    if ($definition) { . ([scriptblock]::Create($definition.Extent.Text)) }
}
$kernelList = $ast.FindAll({ param($n) ($n -is [System.Management.Automation.Language.AssignmentStatementAst]) -and ($n.Left.Extent.Text -eq '$KERNEL_FILES') }, $false) | Select-Object -First 1
Assert-Case ($null -ne $kernelList) 'declares the kernel file list'
if ($kernelList) { . ([scriptblock]::Create($kernelList.Extent.Text)) }
Assert-Case (@($KERNEL_FILES).Count -eq 3) 'kernel list is brainstem.py, agents/basic_agent.py and VERSION'

# The advertised `irm | iex` one-liner passes no arguments, so the variable must pin on
# its own; --version must win over it; a bare --version must refuse, not silently unpin.
$request = Get-PinRequest -ArgList @() -EnvValue ' 0.6.9 '
Assert-Case (($request.Version -eq '0.6.9') -and ($request.Source -eq 'BRAINSTEM_VERSION') -and (-not $request.Error)) 'BRAINSTEM_VERSION alone pins (trimmed)'
$request = Get-PinRequest -ArgList @('--version', 'v0.6.9') -EnvValue ''
Assert-Case (($request.Version -eq 'v0.6.9') -and ($request.Source -eq '--version')) '--version alone pins'
$request = Get-PinRequest -ArgList @('--version', 'brainstem-v0.6.9') -EnvValue '0.6.16'
Assert-Case (($request.Version -eq 'brainstem-v0.6.9') -and ($request.Source -eq '--version')) '--version wins over BRAINSTEM_VERSION'
$request = Get-PinRequest -ArgList @('--version') -EnvValue '0.6.9'
Assert-Case ([bool]$request.Error) '--version without a value is refused'
$request = Get-PinRequest -ArgList @('--VERSION', '0.6.9') -EnvValue ''
Assert-Case ($request.Version -eq '0.6.9') '--version is case-insensitive'
$request = Get-PinRequest -ArgList @() -EnvValue ''
Assert-Case (($request.Version -eq '') -and (-not $request.Error)) 'no pin without the variable or --version'
foreach ($form in @('0.6.9', 'v0.6.9', 'brainstem-v0.6.9')) {
    Assert-Case ((Get-PinBareVersion $form) -eq '0.6.9') "tag form $form names release 0.6.9"
}

# Resolution, the pinned-commit test and the kernel sync run in a real clone. The clone
# uses core.autocrlf=true, the Git for Windows default, so text is checked out as CRLF.
$clone = Join-Path $Work 'ps-pin-clone'
git -c core.autocrlf=true clone --quiet $Origin $clone 2>&1 | Out-Null
Assert-Case (Test-Path (Join-Path $clone '.git')) 'clones the synthetic origin'
Push-Location $clone
try {
    git config core.autocrlf true
    foreach ($form in @('0.0.1', 'v0.0.1', 'brainstem-v0.0.1')) {
        Assert-Case ((Resolve-PinnedTag $form) -eq 'brainstem-v0.0.1') "$form resolves to brainstem-v0.0.1"
    }
    Assert-Case ($null -eq (Resolve-PinnedTag '9.9.9')) 'an unknown version does not resolve'
    Assert-Case ($null -eq (Resolve-PinnedTag 'rapp_brainstem/VERSION')) 'a file name is not a version'
    Assert-Case (-not (Test-AtPinnedCommit 'brainstem-v0.0.1')) 'main is not the pinned commit'

    git checkout --quiet brainstem-v0.0.1 2>&1 | Out-Null
    Assert-Case (Test-AtPinnedCommit 'brainstem-v0.0.1') 'detached at the tag is the pinned commit'
    $agent = 'rapp_brainstem/agents/basic_agent.py'
    Assert-Case ("$(git hash-object --no-filters -- $agent)" -ne "$(git rev-parse "brainstem-v0.0.1:$agent")") 'precondition: autocrlf left the kernel with CRLF bytes'
    $report = Sync-PinnedKernel 'brainstem-v0.0.1' 6>&1 | Out-String
    Assert-Case ($report -match 'byte-for-byte') 'Sync-PinnedKernel reports a byte-exact kernel'
    foreach ($f in $KERNEL_FILES) {
        Assert-Case ("$(git hash-object --no-filters -- $f)" -eq "$(git rev-parse "brainstem-v0.0.1:$f")") "$f matches the tag byte-for-byte"
    }
    Assert-Case (Test-AtPinnedCommit 'brainstem-v0.0.1') 'the synced kernel is still a clean pinned checkout'

    git checkout --quiet -B pin-test-branch brainstem-v0.0.1 2>&1 | Out-Null
    Assert-Case (-not (Test-AtPinnedCommit 'brainstem-v0.0.1')) 'a branch at the tag commit is not pinned (a pull could move it)'
    git checkout --quiet --detach brainstem-v0.0.1 2>&1 | Out-Null
    Add-Content -Path 'rapp_brainstem/brainstem.py' -Value '# local edit'
    Assert-Case (-not (Test-AtPinnedCommit 'brainstem-v0.0.1')) 'an edited kernel is not a pinned checkout'
} finally {
    Pop-Location
}

if ($script:failures -gt 0) { exit 1 }
exit 0
