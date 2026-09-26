# Version-pin tests for install.ps1 (organism gap G23). test_installer.sh runs this
# when PowerShell is available:
#   pwsh -NoProfile -File tests/test_install_pin.ps1 <origin-repo> <work-dir>
# <origin-repo> is the synthetic origin test_installer.sh builds: brainstem-v0.0.1
# (lightweight) and brainstem-v0.0.2 (annotated) tags, main one commit ahead, a v0.0.4
# branch with no tag, releases shipping agents main retired (main ignores one of them)
# and an extras/ folder main lacks. The caller's git config redirects the real repo URL
# to it (url.insteadOf), as in preflight. The pin code is loaded straight out of
# install.ps1 - read as UTF-8 text, the way `irm` delivers it - without running the
# installer. Prints one "PASS <check>" or "FAIL <check>" line per check and exits 1 if
# any check failed.
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
$source = [System.IO.File]::ReadAllText($installer, [System.Text.Encoding]::UTF8)
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$null, [ref]$parseErrors)
Assert-Case (-not $parseErrors) 'install.ps1 parses'

$definitions = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false)
foreach ($name in @('Get-PinRequest', 'Test-PinReleaseForm', 'Get-PinBareVersion', 'Resolve-PinRelease', 'Get-PinCommit',
                    'Test-AtPinnedCommit', 'Get-PinBlockers', 'Move-PinBlockers', 'Restore-PinBlockers', 'Sync-PinnedKernel',
                    'Save-UserState', 'Restore-UserState')) {
    $definition = $definitions | Where-Object { $_.Name -eq $name } | Select-Object -First 1
    Assert-Case ($null -ne $definition) "defines $name"
    if ($definition) { . ([scriptblock]::Create($definition.Extent.Text)) }
}
foreach ($list in @('$KERNEL_FILES', '$USER_STATE_FILES', '$USER_STATE_DIRS', '$REPO_URL')) {
    $assignment = $ast.FindAll({ param($n) ($n -is [System.Management.Automation.Language.AssignmentStatementAst]) -and ($n.Left.Extent.Text -eq $list) }, $false) | Select-Object -First 1
    Assert-Case ($null -ne $assignment) "declares $list"
    if ($assignment) { . ([scriptblock]::Create($assignment.Extent.Text)) }
}
Assert-Case (@($KERNEL_FILES).Count -eq 3) 'kernel list is brainstem.py, agents/basic_agent.py and VERSION'
foreach ($f in @('.copilot_token', '.copilot_session', '.brainstem_model', '.brainstem_secret', 'soul.md', '.env', 'voice.zip')) {
    Assert-Case ($USER_STATE_FILES -contains $f) "user state includes $f"
}
Assert-Case (($USER_STATE_DIRS -contains '.brainstem_data') -and ($USER_STATE_DIRS -contains '.remote_agents')) 'user state includes .brainstem_data and .remote_agents'

# The advertised `irm | iex` one-liner passes no arguments, so the variable must pin on
# its own; --version must win over it; an empty --version (after trimming) must refuse.
$request = Get-PinRequest -ArgList @() -EnvValue ' 0.6.9 '
Assert-Case (($request.Version -eq '0.6.9') -and ($request.Source -eq 'BRAINSTEM_VERSION') -and (-not $request.Error)) 'BRAINSTEM_VERSION alone pins (trimmed)'
$request = Get-PinRequest -ArgList @('--version', 'v0.6.9') -EnvValue ''
Assert-Case (($request.Version -eq 'v0.6.9') -and ($request.Source -eq '--version')) '--version alone pins'
$request = Get-PinRequest -ArgList @('--version', 'brainstem-v0.6.9') -EnvValue '0.6.16'
Assert-Case (($request.Version -eq 'brainstem-v0.6.9') -and ($request.Source -eq '--version')) '--version wins over BRAINSTEM_VERSION'
foreach ($blank in @('', ' ', "`t", " `t `n")) {
    $request = Get-PinRequest -ArgList @('--version', $blank) -EnvValue '0.6.9'
    Assert-Case ([bool]$request.Error) "--version '$($blank.Replace("`t", '\t').Replace("`n", '\n'))' is refused (trimmed first)"
}
$request = Get-PinRequest -ArgList @('--version') -EnvValue '0.6.9'
Assert-Case ([bool]$request.Error) '--version without a value is refused'
$request = Get-PinRequest -ArgList @('--VERSION', '0.6.9') -EnvValue ''
Assert-Case ($request.Version -eq '0.6.9') '--version is case-insensitive'
$request = Get-PinRequest -ArgList @() -EnvValue " `t "
Assert-Case (($request.Version -eq '') -and (-not $request.Error)) 'a whitespace-only BRAINSTEM_VERSION is no pin'
$request = Get-PinRequest -ArgList @() -EnvValue ''
Assert-Case (($request.Version -eq '') -and (-not $request.Error)) 'no pin without the variable or --version'
foreach ($form in @('0.6.9', 'v0.6.9', 'brainstem-v0.6.9')) {
    Assert-Case ((Test-PinReleaseForm $form) -and ((Get-PinBareVersion $form) -eq '0.6.9')) "tag form $form names release 0.6.9"
}

# Only a release tag is a version: branches, HEAD, commits and paths never are.
$lts = 'bded0e1d5044d293f465e3850758f4b012d95078'
foreach ($bad in @('main', 'HEAD', 'HEAD~1', $lts, $lts.Substring(0, 7), 'rapp_brainstem/VERSION', '../../outside',
                   'brainstem-0.6.9', 'V0.6.9', 'Brainstem-v0.6.9', 'refs/tags/brainstem-v0.6.9', 'brainstem-v0.6.9^{commit}',
                   "0.6.9`n", '0.6', '')) {
    Assert-Case (-not (Test-PinReleaseForm $bad)) "'$($bad.Replace("`n", '\n'))' is not a release form"
}

# Resolution runs against the remote (the real URL, redirected to the synthetic origin),
# so it needs no clone; only refs/tags/ count.
$tag1 = "$(git --git-dir=$Origin rev-parse 'brainstem-v0.0.1^{commit}')"
$tag2 = "$(git --git-dir=$Origin rev-parse 'brainstem-v0.0.2^{commit}')"
foreach ($form in @('0.0.1', 'v0.0.1', 'brainstem-v0.0.1')) {
    $release = Resolve-PinRelease -Pin $form -RepoUrl $REPO_URL 6>$null
    Assert-Case (($null -ne $release) -and ($release.Tag -eq 'brainstem-v0.0.1') -and ($release.Commit -eq $tag1)) "$form resolves on the remote to brainstem-v0.0.1 and its commit"
}
$release = Resolve-PinRelease -Pin '0.0.2' -RepoUrl $REPO_URL 6>$null
Assert-Case (($null -ne $release) -and ($release.Commit -eq $tag2)) 'an annotated tag resolves to the commit it names'
$report = Resolve-PinRelease -Pin '9.9.9' -RepoUrl $REPO_URL 6>&1 | Out-String
Assert-Case (($report -match 'Version 9\.9\.9 not found') -and ($report -match 'brainstem-v0\.0\.1') -and ($report -match 'brainstem-v0\.0\.2')) 'an unknown version is refused with the available versions'
foreach ($bad in @('main', 'HEAD', 'HEAD~1', $tag1, $tag1.Substring(0, 7), 'rapp_brainstem/VERSION', 'v0.0.4', '0.0.4')) {
    $release = Resolve-PinRelease -Pin $bad -RepoUrl $REPO_URL 6>$null
    Assert-Case ($null -eq $release) "'$bad' does not resolve (not a release tag)"
}
$release = Resolve-PinRelease -Pin '0.0.1' -RepoUrl (Join-Path $Work 'no-such-origin.git') 6>$null
Assert-Case ($null -eq $release) 'an unreachable remote refuses the pin'

# The pinned-commit test and the kernel sync run in a real clone. The clone uses
# core.autocrlf=true, the Git for Windows default, so text is checked out as CRLF.
$clone = Join-Path $Work 'ps-pin-clone'
git -c core.autocrlf=true clone --quiet --no-tags $Origin $clone 2>&1 | Out-Null
Assert-Case (Test-Path (Join-Path $clone '.git')) 'clones the synthetic origin'
# A shallow clone of main lacks the release commits, so Get-PinCommit has to fetch one.
$shallow = Join-Path $Work 'ps-pin-shallow'
git clone --quiet --depth 1 --no-tags "file://$Origin" $shallow 2>&1 | Out-Null
Push-Location $shallow
try {
    git cat-file -e "$($tag2)^{commit}" 2>$null
    Assert-Case ($LASTEXITCODE -ne 0) 'precondition: the shallow clone lacks the release commit'
    Assert-Case (Get-PinCommit -Tag 'brainstem-v0.0.2' -Commit $tag2 -RepoUrl $REPO_URL) 'fetches a release commit the clone lacks'
    Assert-Case (-not (Get-PinCommit -Tag 'brainstem-v9.9.9' -Commit ('0' * 40) -RepoUrl $REPO_URL)) 'a commit that cannot be fetched is reported'
} finally {
    Pop-Location
}
Push-Location $clone
try {
    git config core.autocrlf true
    Assert-Case (-not (Test-AtPinnedCommit $tag1)) 'main is not the pinned commit'
    # A user's files at paths the release ships: an untracked one and one main ignores.
    Set-Content -Path 'rapp_brainstem/agents/retired_agent.py' -Value 'MINE-RETIRED'
    Set-Content -Path 'rapp_brainstem/agents/legacy_agent.py' -Value 'MINE-LEGACY'
    $blockers = Get-PinBlockers $tag1
    Assert-Case (($null -ne $blockers) -and ($blockers -contains 'rapp_brainstem/agents/retired_agent.py') -and ($blockers -contains 'rapp_brainstem/agents/legacy_agent.py')) 'lists the paths the release adds'
    $kept = Join-Path $Work 'ps-kept'
    Move-PinBlockers -Paths $blockers -Kept $kept
    Assert-Case (-not (Test-Path 'rapp_brainstem/agents/retired_agent.py')) 'sets the user files aside before the switch'
    Assert-Case (Restore-PinBlockers -Paths $blockers -Kept $kept -Tag 'brainstem-v0.0.1' 6>$null) 'puts them back when the switch does not happen'
    Assert-Case (((Get-Content 'rapp_brainstem/agents/retired_agent.py') -eq 'MINE-RETIRED') -and ((Get-Content 'rapp_brainstem/agents/legacy_agent.py') -eq 'MINE-LEGACY')) 'put back byte-for-byte'
    Move-PinBlockers -Paths $blockers -Kept $kept
    git checkout --quiet --detach $tag1 2>&1 | Out-Null
    Assert-Case ($LASTEXITCODE -eq 0) 'the switch succeeds without --force once they are set aside'
    $beside = Restore-PinBlockers -Paths $blockers -Kept $kept -Beside -Tag 'brainstem-v0.0.1' 6>&1 | Out-String
    Assert-Case ($beside -match 'yours is kept beside it') 'reports each file kept beside the release copy'
    $retiredBak = @(Get-ChildItem 'rapp_brainstem/agents' -Filter 'retired_agent.py.bak-*')
    $legacyBak = @(Get-ChildItem 'rapp_brainstem/agents' -Filter 'legacy_agent.py.bak-*')
    Assert-Case (($retiredBak.Count -eq 1) -and ((Get-Content $retiredBak[0].FullName) -eq 'MINE-RETIRED')) 'keeps the untracked user file as <path>.bak-<date>'
    Assert-Case (($legacyBak.Count -eq 1) -and ((Get-Content $legacyBak[0].FullName) -eq 'MINE-LEGACY')) 'keeps the ignored user file as <path>.bak-<date>'
    Assert-Case ((Get-Content 'rapp_brainstem/agents/retired_agent.py') -match 'retired 0\.0\.1') 'the release copy is in place'

    Assert-Case (Test-AtPinnedCommit $tag1) 'detached at the tag is the pinned commit'
    $agent = 'rapp_brainstem/agents/basic_agent.py'
    Assert-Case ("$(git hash-object --no-filters -- $agent)" -ne "$(git rev-parse "$($tag1):$agent")") 'precondition: autocrlf left the kernel with CRLF bytes'
    $report = Sync-PinnedKernel -Commit $tag1 -Tag 'brainstem-v0.0.1' 6>&1 | Out-String
    Assert-Case ($report -match 'Kernel matches brainstem-v0\.0\.1 byte-for-byte') 'Sync-PinnedKernel reports a byte-exact kernel'
    foreach ($f in $KERNEL_FILES) {
        Assert-Case ("$(git hash-object --no-filters -- $f)" -eq "$(git rev-parse "$($tag1):$f")") "$f matches the tag byte-for-byte"
    }
    Assert-Case (Test-AtPinnedCommit $tag1) 'the synced kernel is still a clean pinned checkout'

    git checkout --quiet -B pin-test-branch $tag1 2>&1 | Out-Null
    Assert-Case (-not (Test-AtPinnedCommit $tag1)) 'a branch at the tag commit is not pinned (a pull could move it)'
    git checkout --quiet --detach $tag1 2>&1 | Out-Null
    Add-Content -Path 'rapp_brainstem/brainstem.py' -Value '# local edit'
    Assert-Case (-not (Test-AtPinnedCommit $tag1)) 'an edited kernel is not a pinned checkout'
} finally {
    Pop-Location
}

# A re-clone over a broken install carries every kind of user state over.
$broken = Join-Path $Work 'ps-broken'
$saved = Join-Path $Work 'ps-broken-saved'
$fresh = Join-Path $Work 'ps-fresh'
New-Item -ItemType Directory -Force -Path "$broken\agents", "$broken\.brainstem_data\memory", "$broken\.remote_agents", "$fresh\agents" | Out-Null
foreach ($f in $USER_STATE_FILES) { Set-Content -Path (Join-Path $broken $f) -Value "state $f" }
Set-Content -Path "$broken\.brainstem_data\memory\user_memory.json" -Value 'kept'
Set-Content -Path "$broken\.remote_agents\remote_agent.py" -Value 'remote'
Set-Content -Path "$broken\agents\custom_pin_agent.py" -Value 'mine'
Set-Content -Path "$broken\agents\basic_agent.py" -Value 'old kernel'
Set-Content -Path "$fresh\agents\basic_agent.py" -Value 'release kernel'
Save-UserState -From $broken -To $saved
Remove-Item -Recurse -Force $broken
Restore-UserState -From $saved -To $fresh
foreach ($f in $USER_STATE_FILES) {
    Assert-Case ((Test-Path -LiteralPath (Join-Path $fresh $f)) -and ((Get-Content -LiteralPath (Join-Path $fresh $f)) -eq "state $f")) "a re-clone over a broken install keeps $f"
}
Assert-Case ((Get-Content "$fresh\.brainstem_data\memory\user_memory.json") -eq 'kept') 'a re-clone over a broken install keeps .brainstem_data'
Assert-Case (Test-Path "$fresh\.remote_agents\remote_agent.py") 'a re-clone over a broken install keeps .remote_agents'
Assert-Case ((Get-Content "$fresh\agents\custom_pin_agent.py") -eq 'mine') 'a re-clone over a broken install keeps custom agents'
Assert-Case ((Get-Content "$fresh\agents\basic_agent.py") -eq 'release kernel') 'the re-clone keeps the release basic_agent.py'

if ($script:failures -gt 0) { exit 1 }
exit 0
