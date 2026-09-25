#!/bin/bash
# Tests for RAPP Brainstem installer and server
# Run: bash tests/test_installer.sh

set -e
PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

pass() { PASS=$((PASS + 1)); echo "  ✓ $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  ✗ $1"; }

echo "=== RAPP Brainstem Tests ==="
echo ""

# ── install.sh tests ──────────────────────────────────────────────────────────

echo "--- install.sh ---"

if bash -n "$REPO_ROOT/install.sh" 2>/dev/null; then
    pass "install.sh is valid bash"
else
    fail "install.sh has syntax errors"
fi

if grep -q "RAPP Brainstem" "$REPO_ROOT/install.sh"; then
    pass "install.sh has brainstem branding"
else
    fail "install.sh missing brainstem branding"
fi

if grep -q '\.brainstem' "$REPO_ROOT/install.sh" && ! grep -q 'RAPP_HOME=.*\.rapp"' "$REPO_ROOT/install.sh"; then
    pass "install.sh targets ~/.brainstem"
else
    fail "install.sh should target ~/.brainstem"
fi

if grep -q 'BRAINSTEM_BIN.*local/bin' "$REPO_ROOT/install.sh" && grep -q 'brainstem.*WRAPPER' "$REPO_ROOT/install.sh"; then
    pass "install.sh creates brainstem CLI"
else
    fail "install.sh should create brainstem CLI wrapper"
fi

if grep -q 'rapp-installer.git' "$REPO_ROOT/install.sh" && ! grep -q 'RAPPAI' "$REPO_ROOT/install.sh"; then
    pass "install.sh clones public repo"
else
    fail "install.sh should clone public rapp-installer repo"
fi

echo ""

# ── install.ps1 tests ────────────────────────────────────────────────────────

echo "--- install.ps1 ---"

if grep -q "RAPP Brainstem" "$REPO_ROOT/install.ps1"; then
    pass "install.ps1 has brainstem branding"
else
    fail "install.ps1 missing brainstem branding"
fi

if grep -q '\.brainstem' "$REPO_ROOT/install.ps1"; then
    pass "install.ps1 targets ~/.brainstem"
else
    fail "install.ps1 should target ~/.brainstem"
fi

echo ""

# ── install.cmd tests ────────────────────────────────────────────────────────

echo "--- install.cmd ---"

if grep -qi "brainstem" "$REPO_ROOT/install.cmd"; then
    pass "install.cmd references brainstem"
else
    fail "install.cmd should reference brainstem"
fi

echo ""

# ── version pin (install.sh + install.ps1) ───────────────────────────────────
# Organism gap G23: a pin must work through the advertised one-liners (the
# BRAINSTEM_VERSION variable; --version wins over it), refuse an unknown version before
# anything changes, land exactly on the tag commit on fresh installs and upgrades, keep
# user files, and leave the kernel byte-exact even under core.autocrlf=true (the Git for
# Windows default). The REAL install.sh runs against a synthetic tagged origin through
# the same url.insteadOf redirect preflight uses; a python test double stops every run
# at the venv step, right after the source checkout (no pip, no network, no server).

echo "--- version pin ---"

PIN_SANDBOX=$(mktemp -d "${TMPDIR:-/tmp}/brainstem-pin-XXXXXX")
PIN_ORIGIN="$PIN_SANDBOX/origin.git"
PIN_SHIMS="$PIN_SANDBOX/shims"
PIN_GITCONFIG="$PIN_SANDBOX/gitconfig"
PIN_KERNEL="rapp_brainstem/brainstem.py rapp_brainstem/agents/basic_agent.py rapp_brainstem/VERSION"

# Test-side git runs sandboxed too: no global/system config, hooks or identity leak in.
pgit() { GIT_CONFIG_GLOBAL="$PIN_GITCONFIG" GIT_CONFIG_NOSYSTEM=1 git "$@"; }
pin_git() { pgit -c user.name=pin-test -c user.email= -c core.autocrlf=false -c init.defaultBranch=main "$@"; }

# Three releases: v0.0.1 and v0.0.2 tagged, main one commit ahead. basic_agent.py never
# changes (like brainstem-v0.6.9 -> main), so a switch alone would not rewrite it.
pin_build_origin() {
    local seed="$PIN_SANDBOX/seed" v
    mkdir -p "$seed/rapp_brainstem/agents" "$PIN_SHIMS" || return 1
    pin_git init --quiet "$seed" || return 1
    printf 'class BasicAgent:\n    pass\n' > "$seed/rapp_brainstem/agents/basic_agent.py"
    printf 'print("bundled")\n' > "$seed/rapp_brainstem/agents/bundled_agent.py"
    for v in 0.0.1 0.0.2 0.0.3; do
        printf '%s\n' "$v" > "$seed/rapp_brainstem/VERSION"
        printf 'print("kernel %s")\n' "$v" > "$seed/rapp_brainstem/brainstem.py"
        printf 'default soul %s\n' "$v" > "$seed/rapp_brainstem/soul.md"
        pin_git -C "$seed" add -A || return 1
        pin_git -C "$seed" commit --quiet -m "release: v$v" || return 1
        [ "$v" = 0.0.3 ] || pin_git -C "$seed" tag "brainstem-v$v" || return 1
    done
    pin_git -C "$seed" branch -M main || return 1
    pin_git clone --quiet --bare "$seed" "$PIN_ORIGIN" || return 1
    pgit config --file "$PIN_GITCONFIG" "url.file://$PIN_ORIGIN.insteadOf" "https://github.com/kody-w/rapp-installer.git" || return 1
    # Test doubles: python answers only the installer's version probe; nothing reaches the network.
    printf '#!/bin/bash\ncase "$*" in *version_info*) echo 3.11; exit 0 ;; esac\nexit 1\n' > "$PIN_SHIMS/python3.11"
    printf '#!/bin/bash\necho "gh version 2.0.0 (test double)"\n' > "$PIN_SHIMS/gh"
    printf '#!/bin/bash\nexit 7\n' > "$PIN_SHIMS/curl"
    for v in brew sudo apt-get; do printf '#!/bin/bash\nexit 1\n' > "$PIN_SHIMS/$v"; done
    chmod +x "$PIN_SHIMS"/* || return 1
}

# pin_run <home> <log> [VAR=value ...] -- [installer args ...]; exit status in PIN_RC.
pin_run() {
    local home="$1" log="$2" envs=()
    shift 2
    while [ $# -gt 0 ] && [ "$1" != "--" ]; do envs+=("$1"); shift; done
    [ "${1:-}" = "--" ] && shift
    PIN_RC=0
    env -u BRAINSTEM_VERSION HOME="$home" TMPDIR="$PIN_SANDBOX" GIT_CONFIG_GLOBAL="$PIN_GITCONFIG" \
        GIT_CONFIG_NOSYSTEM=1 PATH="$PIN_SHIMS:$PATH" ${envs[@]+"${envs[@]}"} \
        bash "$REPO_ROOT/install.sh" "$@" >"$log" 2>&1 </dev/null || PIN_RC=$?
}

# An existing install at origin main with a user's soul edit, .env and custom agent.
# With "crlf" it is checked out with core.autocrlf=true, like a Windows machine.
pin_seed_install() {
    local src="$1/.brainstem/src" crlf=false
    [ "${2:-}" = crlf ] && crlf=true
    pgit -c core.autocrlf=$crlf clone --quiet "$PIN_ORIGIN" "$src" || return 1
    pgit -C "$src" config core.autocrlf $crlf
    printf 'PIN-SOUL-MARKER\n' >> "$src/rapp_brainstem/soul.md"
    printf 'PIN-ENV-MARKER=1\n' > "$src/rapp_brainstem/.env"
    printf 'print("mine")\n' > "$src/rapp_brainstem/agents/custom_pin_agent.py"
}

pin_tag_commit() { pgit --git-dir="$PIN_ORIGIN" rev-parse "brainstem-v0.0.1^{commit}"; }
pin_at_tag() {  # HEAD is the brainstem-v0.0.1 commit, detached (no pull can move it)
    local src="$1/.brainstem/src"
    [ "$(pgit -C "$src" rev-parse HEAD 2>/dev/null)" = "$(pin_tag_commit)" ] \
        && ! pgit -C "$src" symbolic-ref --quiet HEAD >/dev/null 2>&1
}
pin_kernel_exact() {  # raw bytes on disk == the tag's blobs
    local src="$1/.brainstem/src" f
    for f in $PIN_KERNEL; do
        [ "$(pgit -C "$src" hash-object --no-filters -- "$f" 2>/dev/null)" = "$(pgit --git-dir="$PIN_ORIGIN" rev-parse "brainstem-v0.0.1:$f")" ] || return 1
    done
}
pin_stopped_at_venv() { grep -q "Failed to create virtual environment" "$1"; }

if pin_build_origin; then
    H="$PIN_SANDBOX/h-env"; L="$PIN_SANDBOX/h-env.log"
    pin_run "$H" "$L" "BRAINSTEM_VERSION= 0.0.1 " --
    if grep -q "Pinning to version: 0.0.1 (from BRAINSTEM_VERSION)" "$L" && pin_at_tag "$H" \
       && pin_kernel_exact "$H" && pin_stopped_at_venv "$L"; then
        pass "install.sh: BRAINSTEM_VERSION alone pins a fresh install to the tag commit"
    else
        fail "install.sh: BRAINSTEM_VERSION pin (rc=$PIN_RC): $(tail -5 "$L")"
    fi

    H="$PIN_SANDBOX/h-arg"; L="$PIN_SANDBOX/h-arg.log"
    pin_run "$H" "$L" -- --version v0.0.1
    if grep -q "(from --version)" "$L" && pin_at_tag "$H" && pin_kernel_exact "$H"; then
        pass "install.sh: --version v0.0.1 resolves to brainstem-v0.0.1"
    else
        fail "install.sh: --version v-form pin (rc=$PIN_RC): $(tail -5 "$L")"
    fi

    H="$PIN_SANDBOX/h-wins"; L="$PIN_SANDBOX/h-wins.log"
    pin_run "$H" "$L" BRAINSTEM_VERSION=9.9.9 -- --version brainstem-v0.0.1
    if pin_at_tag "$H" && pin_kernel_exact "$H"; then
        pass "install.sh: --version wins over BRAINSTEM_VERSION"
    else
        fail "install.sh: --version precedence (rc=$PIN_RC): $(tail -5 "$L")"
    fi

    H="$PIN_SANDBOX/h-unknown"; L="$PIN_SANDBOX/h-unknown.log"
    pin_run "$H" "$L" BRAINSTEM_VERSION=0.0.1 -- --version 9.9.9
    if [ "$PIN_RC" -ne 0 ] && grep -q "Version 9.9.9 not found" "$L" && grep -q "brainstem-v0.0.1" "$L" \
       && ! pin_stopped_at_venv "$L"; then
        pass "install.sh: an unknown pin is refused with the available versions"
    else
        fail "install.sh: unknown pin refusal (rc=$PIN_RC): $(tail -5 "$L")"
    fi

    H="$PIN_SANDBOX/h-novalue"; L="$PIN_SANDBOX/h-novalue.log"
    pin_run "$H" "$L" -- --version
    if [ "$PIN_RC" -ne 0 ] && grep -q "needs a value" "$L" && [ ! -e "$H/.brainstem" ]; then
        pass "install.sh: --version without a value is refused before anything changes"
    else
        fail "install.sh: bare --version (rc=$PIN_RC): $(tail -5 "$L")"
    fi

    H="$PIN_SANDBOX/h-file"; L="$PIN_SANDBOX/h-file.log"
    pin_run "$H" "$L" -- --version rapp_brainstem/VERSION
    if [ "$PIN_RC" -ne 0 ] && grep -q "not found" "$L" && ! pin_stopped_at_venv "$L"; then
        pass "install.sh: a file name is not accepted as a version"
    else
        fail "install.sh: file-name pin (rc=$PIN_RC): $(tail -5 "$L")"
    fi

    H="$PIN_SANDBOX/h-upgrade"; L="$PIN_SANDBOX/h-upgrade.log"
    S="$H/.brainstem/src/rapp_brainstem"
    if pin_seed_install "$H" crlf; then
        pin_run "$H" "$L" -- --version brainstem-v0.0.1
        if pin_at_tag "$H" && pin_kernel_exact "$H" && grep -q "PIN-SOUL-MARKER" "$S/soul.md" \
           && grep -q "PIN-ENV-MARKER" "$S/.env" && [ -f "$S/agents/custom_pin_agent.py" ] \
           && grep -q $'\r' "$S/agents/bundled_agent.py" && pin_stopped_at_venv "$L"; then
            pass "install.sh: pinned upgrade lands on the tag, byte-exact kernel under autocrlf, user files kept"
        else
            fail "install.sh: pinned upgrade (rc=$PIN_RC): $(tail -8 "$L")"
        fi
        STASHES=$(pgit -C "$H/.brainstem/src" stash list | wc -l)
        L="$PIN_SANDBOX/h-upgrade-again.log"
        pin_run "$H" "$L" -- --version 0.0.1
        if grep -q "Already on v0.0.1 (brainstem-v0.0.1)" "$L" && pin_at_tag "$H" && pin_kernel_exact "$H" \
           && [ "$(pgit -C "$H/.brainstem/src" stash list | wc -l)" = "$STASHES" ] && grep -q "PIN-SOUL-MARKER" "$S/soul.md"; then
            pass "install.sh: re-running the same pin changes nothing"
        else
            fail "install.sh: pinned re-run (rc=$PIN_RC): $(tail -5 "$L")"
        fi
    else
        fail "install.sh: could not seed an existing install"
    fi

    H="$PIN_SANDBOX/h-refuse"; L="$PIN_SANDBOX/h-refuse.log"
    S="$H/.brainstem/src/rapp_brainstem"
    if pin_seed_install "$H"; then
        BEFORE=$(pgit -C "$H/.brainstem/src" rev-parse HEAD)
        pin_run "$H" "$L" -- --version 9.9.9
        if [ "$PIN_RC" -ne 0 ] && grep -q "Version 9.9.9 not found" "$L" \
           && [ "$(pgit -C "$H/.brainstem/src" rev-parse HEAD)" = "$BEFORE" ] \
           && pgit -C "$H/.brainstem/src" symbolic-ref --quiet HEAD >/dev/null \
           && [ -z "$(pgit -C "$H/.brainstem/src" stash list)" ] && grep -q "PIN-SOUL-MARKER" "$S/soul.md" \
           && grep -q "PIN-ENV-MARKER" "$S/.env" && [ -f "$S/agents/custom_pin_agent.py" ]; then
            pass "install.sh: an unknown pin on an existing install leaves it and the user's files untouched"
        else
            fail "install.sh: unknown pin on upgrade (rc=$PIN_RC): $(tail -5 "$L")"
        fi
    else
        fail "install.sh: could not seed an existing install"
    fi

    H="$PIN_SANDBOX/h-broken"; L="$PIN_SANDBOX/h-broken.log"
    S="$H/.brainstem/src/rapp_brainstem"
    mkdir -p "$S/agents" "$S/.brainstem_data"
    printf 'BROKEN-SOUL-MARKER\n' > "$S/soul.md"
    printf 'BROKEN-ENV-MARKER=1\n' > "$S/.env"
    printf 'print("mine")\n' > "$S/agents/custom_pin_agent.py"
    printf '{"memory": "kept"}\n' > "$S/.brainstem_data/memory.json"
    pin_run "$H" "$L" -- --version 9.9.9
    if [ "$PIN_RC" -ne 0 ] && grep -q "Version 9.9.9 not found" "$L" && grep -q "BROKEN-SOUL-MARKER" "$S/soul.md" \
       && grep -q "BROKEN-ENV-MARKER" "$S/.env" && [ -f "$S/agents/custom_pin_agent.py" ] \
       && grep -q "kept" "$S/.brainstem_data/memory.json"; then
        pass "install.sh: a refused pin over a broken install still restores the user's files"
    else
        fail "install.sh: refused pin over a broken install (rc=$PIN_RC): $(tail -5 "$L")"
    fi

    H="$PIN_SANDBOX/h-branch"; L="$PIN_SANDBOX/h-branch.log"
    if pin_seed_install "$H" && pgit -C "$H/.brainstem/src" reset --quiet --hard brainstem-v0.0.1; then
        pin_run "$H" "$L" -- --version 0.0.1
        if pin_at_tag "$H" && pin_kernel_exact "$H"; then
            pass "install.sh: a branch whose VERSION already matches is still switched to the detached tag"
        else
            fail "install.sh: same-VERSION branch (rc=$PIN_RC): $(tail -5 "$L")"
        fi
    else
        fail "install.sh: could not seed a same-VERSION branch"
    fi

    PS_RUNNER=""
    if command -v pwsh >/dev/null 2>&1; then PS_RUNNER=pwsh
    elif command -v powershell >/dev/null 2>&1; then PS_RUNNER=powershell
    fi
    if [ -n "$PS_RUNNER" ]; then
        PS_OUT=$("$PS_RUNNER" -NoProfile -NonInteractive -File "$REPO_ROOT/tests/test_install_pin.ps1" "$PIN_ORIGIN" "$PIN_SANDBOX" 2>&1) || true
        while IFS= read -r line; do
            case "$line" in
                "PASS "*) pass "install.ps1: ${line#PASS }" ;;
                "FAIL "*) fail "install.ps1: ${line#FAIL }" ;;
            esac
        done <<< "$PS_OUT"
        if ! printf '%s\n' "$PS_OUT" | grep -q '^PASS '; then
            fail "install.ps1 pin tests did not run: $PS_OUT"
        fi
    else
        echo "  - install.ps1 pin tests skipped (no pwsh or powershell on PATH)"
    fi
else
    fail "could not build the synthetic pin origin"
fi
rm -rf "$PIN_SANDBOX"

echo ""

# ── skill.md tests ────────────────────────────────────────────────────────────

echo "--- skill.md ---"

if head -1 "$REPO_ROOT/skill.md" | grep -q '^---'; then
    pass "skill.md has YAML frontmatter"
else
    fail "skill.md missing YAML frontmatter"
fi

TIER_COUNT=$(grep -cE "^## Tier [0-9]" "$REPO_ROOT/skill.md" || true)
if [ "$TIER_COUNT" -ge 3 ]; then
    pass "skill.md has all 3 tiers"
else
    fail "skill.md missing tier content (found $TIER_COUNT)"
fi

# Pause points are the per-tier gates that stop autonomous execution and hand back
# to the user ("Do not proceed…", "Wait for…", "Only pause and ask…").
PAUSE_COUNT=$(grep -cE "Do not proceed|Wait for|Only pause" "$REPO_ROOT/skill.md" || true)
if [ "$PAUSE_COUNT" -ge 3 ]; then
    pass "skill.md has $PAUSE_COUNT pause points"
else
    fail "skill.md needs at least 3 pause points (found $PAUSE_COUNT)"
fi

if grep -q 'state.json' "$REPO_ROOT/skill.md"; then
    pass "skill.md saves state to disk"
else
    fail "skill.md should save state like Moltbook pattern"
fi

if grep -q "Do not proceed" "$REPO_ROOT/skill.md"; then
    pass "skill.md gates tier progression"
else
    fail "skill.md should gate tier progression"
fi

echo ""

# ── plugin marketplace + repository policy tests ─────────────────────────────

echo "--- Copilot plugin marketplace ---"

if python3 - "$REPO_ROOT" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
marketplace = json.loads(
    (root / ".claude-plugin" / "marketplace.json").read_text()
)
plugin = json.loads(
    (root / ".claude-plugin" / "plugin.json").read_text()
)
assert marketplace["name"] == "brainstem"
assert marketplace["plugins"][0]["name"] == "rapp"
assert marketplace["plugins"][0]["version"] == plugin["version"]
assert (root / "skills" / "rapp-bootstrap" / "SKILL.md").is_file()
PY
then
    pass "Copilot marketplace and plugin manifests agree"
else
    fail "Copilot marketplace or plugin manifest is invalid"
fi

for policy_file in CONTRIBUTING.md CODE_OF_CONDUCT.md SECURITY.md SUPPORT.md MARKETPLACE_CHARTER.md; do
    if [ -s "$REPO_ROOT/$policy_file" ]; then
        pass "repository policy present: $policy_file"
    else
        fail "repository policy missing: $policy_file"
    fi
done

echo ""

# ── index.html tests ─────────────────────────────────────────────────────────

echo "--- index.html ---"

# The landing page names Tier 2 by its installer path ("Hippocampus") or its tier
# metaphor ("Spinal Cord") — accept either so a vocabulary choice doesn't fail the test.
if grep -q "Brainstem" "$REPO_ROOT/index.html" \
   && { grep -q "Spinal Cord" "$REPO_ROOT/index.html" || grep -q "Hippocampus" "$REPO_ROOT/index.html"; } \
   && grep -q "Nervous System" "$REPO_ROOT/index.html"; then
    pass "index.html has all 3 tiers"
else
    fail "index.html missing tier content"
fi

if grep -q "curl -fsSL" "$REPO_ROOT/index.html"; then
    pass "index.html has one-liner install command"
else
    fail "index.html missing one-liner"
fi

if grep -q "localhost:7071" "$REPO_ROOT/index.html"; then
    pass "index.html has health check"
else
    fail "index.html missing health check"
fi

echo ""

# ── README.md tests ───────────────────────────────────────────────────────────

echo "--- README.md ---"

if head -5 "$REPO_ROOT/README.md" | grep -q "Brainstem"; then
    pass "README.md leads with brainstem"
else
    fail "README.md should lead with brainstem"
fi

if grep -q "curl -fsSL" "$REPO_ROOT/README.md"; then
    pass "README.md has one-liner"
else
    fail "README.md missing one-liner"
fi

if grep -q "Tier 1" "$REPO_ROOT/README.md" && grep -q "Tier 2" "$REPO_ROOT/README.md" && grep -q "Tier 3" "$REPO_ROOT/README.md"; then
    pass "README.md has all 3 tiers"
else
    fail "README.md missing tier content"
fi

echo ""

# ── copilot-instructions.md tests ────────────────────────────────────────────

echo "--- .github/copilot-instructions.md ---"

if grep -q "Brainstem" "$REPO_ROOT/.github/copilot-instructions.md" && grep -q "Spinal Cord" "$REPO_ROOT/.github/copilot-instructions.md"; then
    pass "copilot-instructions.md has progressive architecture"
else
    fail "copilot-instructions.md missing progressive architecture"
fi

if grep -q "pytest" "$REPO_ROOT/.github/copilot-instructions.md"; then
    pass "copilot-instructions.md has test commands"
else
    fail "copilot-instructions.md missing test commands"
fi

echo ""

# ── brainstem server tests ────────────────────────────────────────────────────

echo "--- brainstem server ---"

if [ -f "$REPO_ROOT/rapp_brainstem/requirements.txt" ]; then
    pass "requirements.txt exists"
else
    fail "requirements.txt missing"
fi

for endpoint in "/chat" "/health" "/login" "/models" "/agents" "/version"; do
    if grep -q "\"$endpoint\"" "$REPO_ROOT/rapp_brainstem/brainstem.py"; then
        pass "brainstem.py has $endpoint endpoint"
    else
        fail "brainstem.py missing $endpoint endpoint"
    fi
done

# BasicAgent lives in agents/ (also mirrored to the repo copy the shim loads).
if grep -q "def perform" "$REPO_ROOT/rapp_brainstem/agents/basic_agent.py" && grep -q "def to_tool" "$REPO_ROOT/rapp_brainstem/agents/basic_agent.py"; then
    pass "basic_agent.py has perform() and to_tool()"
else
    fail "basic_agent.py missing required methods"
fi

echo ""

# ── bundled agents ────────────────────────────────────────────────────────────

echo "--- bundled agents ---"

# Each bundled agent file must define a class that loads and exposes a valid tool
# schema. This is the contract every *_agent.py must satisfy to be discoverable.
for agent_file in manage_memory_agent context_memory_agent hacker_news_agent; do
    if [ -f "$REPO_ROOT/rapp_brainstem/agents/${agent_file}.py" ]; then
        pass "bundled agent present: ${agent_file}.py"
    else
        fail "bundled agent missing: ${agent_file}.py"
    fi
done

# Drive the REAL loader (which registers the utils/basic_agent shims the memory
# agents import) so this exercises the same path a live /chat request would — but
# against a temp dir holding only the GIT-TRACKED agents, so a local drop-in can't
# fail (or pip-install mid-run during) a check of the BUNDLED set. The `|| true`
# keeps a failure reportable instead of aborting the whole suite under set -e.
TMP_AGENTS=$(mktemp -d "${TMPDIR:-/tmp}/brainstem-agents-XXXXXX")
for f in "$REPO_ROOT"/rapp_brainstem/agents/*.py; do
    base=$(basename "$f")
    if (cd "$REPO_ROOT" && git ls-files --error-unmatch "rapp_brainstem/agents/$base" >/dev/null 2>&1); then
        cp "$f" "$TMP_AGENTS/"
    fi
done
# Not a git checkout (tarball)? Fall back to everything rather than testing nothing.
if ! ls "$TMP_AGENTS"/*_agent.py >/dev/null 2>&1; then
    cp "$REPO_ROOT"/rapp_brainstem/agents/*.py "$TMP_AGENTS/" 2>/dev/null || true
fi
AGENT_TEST=$(cd "$REPO_ROOT/rapp_brainstem" && AGENTS_PATH="$TMP_AGENTS" python3 -c "
import sys
sys.path.insert(0, '.')
import brainstem
agents = brainstem.load_agents()
names = set(agents)
assert 'ManageMemory' in names and 'ContextMemory' in names, names
for a in agents.values():
    t = a.to_tool()
    assert t['type'] == 'function' and t['function']['name'], t
print('ok')
" 2>&1) || true
rm -rf "$TMP_AGENTS"
if [ "$(printf '%s' "$AGENT_TEST" | tail -1)" = "ok" ]; then
    pass "bundled agents load and expose valid tool schemas"
else
    fail "bundled agent runtime test failed: $AGENT_TEST"
fi

echo ""

# ── docs/ & tracking tests ───────────────────────────────────────────────────

echo "--- docs & tracking ---"

if [ -f "$REPO_ROOT/docs/index.html" ] && grep -q "Brainstem" "$REPO_ROOT/docs/index.html"; then
    pass "docs/index.html has brainstem content"
else
    fail "docs/index.html missing or stale"
fi

if [ -f "$REPO_ROOT/docs/install.sh" ] && grep -q "brainstem" "$REPO_ROOT/docs/install.sh" -i; then
    pass "docs/install.sh exists for GitHub Pages curl"
else
    fail "docs/install.sh missing (needed for curl one-liner via GitHub Pages)"
fi

if [ ! -f "$REPO_ROOT/docs/copilot-install.html" ]; then
    pass "stale docs/copilot-install.html removed"
else
    fail "docs/copilot-install.html should be removed (stale)"
fi

if grep -q ".brainstem_data" "$REPO_ROOT/.gitignore" && grep -q ".remote_agents" "$REPO_ROOT/.gitignore"; then
    pass ".gitignore excludes runtime artifacts"
else
    fail ".gitignore should exclude .brainstem_data/ and .remote_agents/"
fi

echo ""

# ── unit tests ────────────────────────────────────────────────────────────────

echo "--- unit tests (tests/) ---"
cd "$REPO_ROOT/rapp_brainstem"
if python3 -m pytest tests/ -x --tb=short -q 2>&1; then
    pass "unit tests passed"
else
    fail "unit tests failed"
fi

echo ""

# ── Summary ───────────────────────────────────────────────────────────────────

TOTAL=$((PASS + FAIL))
echo "=== Results: $PASS/$TOTAL passed ==="
if [ "$FAIL" -gt 0 ]; then
    echo "  $FAIL test(s) failed"
    exit 1
else
    echo "  All tests passed! ✓"
    exit 0
fi
