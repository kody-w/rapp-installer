#!/bin/bash
set -e

# RAPP Brainstem Installer
# Usage: curl -fsSL https://kody-w.github.io/rapp-installer/install.sh | bash
# Pin a version: curl ... install.sh | bash -s -- --version v0.6.0
#            or: curl ... install.sh | BRAINSTEM_VERSION=0.6.0 bash
# A pin names a release tag in any form we ship (0.6.0, v0.6.0, brainstem-v0.6.0), never a
# branch or a commit; --version wins over the variable.

BRAINSTEM_HOME="$HOME/.brainstem"
BRAINSTEM_BIN="$HOME/.local/bin"
VENV_DIR="$BRAINSTEM_HOME/venv"
REPO_URL="https://github.com/kody-w/rapp-installer.git"
REMOTE_VERSION_URL="https://raw.githubusercontent.com/kody-w/rapp-installer/main/rapp_brainstem/VERSION"
# The version pin (set in main): what was asked for and where it came from, then the
# release tag and commit it resolved to on the remote.
PIN_VERSION=""
PIN_SOURCE=""
PIN_ERROR=""
PIN_TAG=""
PIN_COMMIT=""
# The kernel ("grail") files a pinned install must reproduce byte-for-byte: the set
# RAPP's KERNEL_PIN.json freezes by SHA-256.
KERNEL_FILES="rapp_brainstem/brainstem.py rapp_brainstem/agents/basic_agent.py rapp_brainstem/VERSION"
# User state the source tree holds outside git (in rapp_brainstem/): soul, config, tokens
# and session, the LAN secret, the model pick, voice config, memories and remote agents
# (custom agents are handled with them). A switch leaves it in place; a re-clone over a
# broken install (src without .git) carries it over (save_user_state/restore_user_state).
USER_STATE_FILES="soul.md .env .copilot_token .copilot_session .brainstem_secret .brainstem_model voice.zip"
USER_STATE_DIRS=".brainstem_data .remote_agents"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

read_input() {
    local prompt="$1" default="$2" result
    if [ -t 0 ]; then
        read -p "$prompt" result
    else
        read -p "$prompt" result < /dev/tty
    fi
    echo "${result:-$default}"
}

print_banner() {
    echo ""
    echo -e "${CYAN}"
    echo "  🧠 RAPP Brainstem"
    echo -e "${NC}"
    echo "  Local-first AI agent server"
    echo "  Powered by GitHub Copilot — no API keys needed"
    echo ""
}

detect_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then echo "macos"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then echo "linux"
    else echo "unknown"
    fi
}

# Ensure Homebrew is on PATH — curl|bash sessions don't source shell profiles
ensure_brew_on_path() {
    if command -v brew &> /dev/null; then return 0; fi
    if [[ -x "/opt/homebrew/bin/brew" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x "/usr/local/bin/brew" ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
}

find_python() {
    for cmd in python3.11 python3.12 python3.13 python3; do
        if command -v "$cmd" &> /dev/null; then
            version=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null) || continue
            major=$(echo "$version" | cut -d. -f1)
            minor=$(echo "$version" | cut -d. -f2)
            if [[ -n "$major" && -n "$minor" ]] && [ "$major" -ge 3 ] 2>/dev/null && [ "$minor" -ge 11 ] 2>/dev/null; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    if [[ "$(detect_os)" == "macos" ]]; then
        for p in /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
            if [[ -x "$p" ]]; then echo "$p"; return 0; fi
        done
    fi
    return 1
}

install_python() {
    local os_type=$(detect_os)
    echo -e "  ${YELLOW}Installing Python 3.11...${NC}"
    if [[ "$os_type" == "macos" ]]; then
        if ! command -v brew &> /dev/null; then
            echo -e "  ${YELLOW}Installing Homebrew first...${NC}"
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            if [[ -f "/opt/homebrew/bin/brew" ]]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi
        fi
        brew install python@3.11
        export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
    elif [[ "$os_type" == "linux" ]]; then
        if command -v apt-get &> /dev/null; then
            sudo apt-get update && sudo apt-get install -y python3.11 python3.11-venv python3-pip
        elif command -v dnf &> /dev/null; then
            sudo dnf install -y python3.11 python3-pip
        else
            echo -e "  ${RED}✗${NC} Cannot auto-install Python 3.11 on this system"
            echo "    Install manually from https://python.org"
            exit 1
        fi
    fi
}

# Compare two semver strings. Returns 0 if $1 > $2, 1 otherwise.
version_gt() {
    local IFS=.
    local i a=($1) b=($2)
    for ((i=0; i<${#a[@]}; i++)); do
        local va=${a[i]:-0}
        local vb=${b[i]:-0}
        if (( va > vb )); then return 0; fi
        if (( va < vb )); then return 1; fi
    done
    return 1  # equal
}

check_for_upgrade() {
    local version_file="$BRAINSTEM_HOME/src/rapp_brainstem/VERSION"

    # No existing install — always proceed
    if [ ! -f "$version_file" ]; then
        return 0
    fi

    local local_version
    local_version=$(cat "$version_file" 2>/dev/null | tr -d '[:space:]')

    # Fetch remote version
    local remote_version
    remote_version=$(curl -fsSL "$REMOTE_VERSION_URL" 2>/dev/null | tr -d '[:space:]') || true

    if [[ -z "$remote_version" ]]; then
        echo -e "  ${YELLOW}⚠${NC} Could not check remote version — upgrading anyway"
        return 0
    fi

    echo -e "  Local version:  ${CYAN}${local_version}${NC}"
    echo -e "  Remote version: ${CYAN}${remote_version}${NC}"

    if [[ "$local_version" == "$remote_version" ]]; then
        echo ""
        echo -e "  ${GREEN}✓ Already up to date (v${local_version})${NC}"
        echo ""
        return 1  # no upgrade needed
    fi

    if version_gt "$remote_version" "$local_version"; then
        echo -e "  ${YELLOW}⬆${NC} Upgrade available: ${local_version} → ${remote_version}"
        return 0
    fi

    echo -e "  ${GREEN}✓ Already up to date (v${local_version})${NC}"
    echo ""
    return 1
}

# Git: report it, or install it. check_prereqs runs this; a pinned install runs it first
# on a machine without git, because checking the pin against the remote needs git.
check_git() {
    if command -v git &> /dev/null; then
        echo -e "  ${GREEN}✓${NC} Git $(git --version | cut -d' ' -f3)"
    else
        echo -e "  ${YELLOW}⚠${NC} Git not found, installing..."
        if [[ "$(detect_os)" == "macos" ]]; then
            xcode-select --install 2>/dev/null || brew install git
        elif command -v apt-get &> /dev/null; then
            sudo apt-get update && sudo apt-get install -y git
        else
            echo -e "  ${RED}✗${NC} Git required — install from https://git-scm.com"
            exit 1
        fi
    fi
}

check_prereqs() {
    echo "Checking prerequisites..."

    # On macOS, ensure Homebrew is on PATH (curl|bash doesn't source shell profiles)
    if [[ "$(detect_os)" == "macos" ]]; then
        ensure_brew_on_path
    fi

    # Python 3.11+
    PYTHON_CMD=$(find_python) || true
    if [[ -n "$PYTHON_CMD" ]]; then
        version=$("$PYTHON_CMD" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        echo -e "  ${GREEN}✓${NC} Python $version ($PYTHON_CMD)"
    else
        echo -e "  ${YELLOW}⚠${NC} Python 3.11+ not found"
        install_python
        PYTHON_CMD=$(find_python) || true
        if [[ -z "$PYTHON_CMD" ]]; then
            echo -e "  ${RED}✗${NC} Failed to install Python 3.11"
            exit 1
        fi
        version=$("$PYTHON_CMD" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        echo -e "  ${GREEN}✓${NC} Python $version installed"
    fi
    export PYTHON_CMD

    # Git
    check_git

    # GitHub CLI (required for Copilot token auth)
    if command -v gh &> /dev/null; then
        echo -e "  ${GREEN}✓${NC} GitHub CLI $(gh --version | head -1 | awk '{print $3}')"
    else
        echo -e "  ${YELLOW}⚠${NC} GitHub CLI not found, installing..."
        local os_type=$(detect_os)
        if [[ "$os_type" == "macos" ]]; then
            if command -v brew &> /dev/null; then
                brew install gh
            else
                echo -e "  ${YELLOW}⚠${NC} Installing Homebrew first..."
                /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
                ensure_brew_on_path
                brew install gh
            fi
        elif [[ "$os_type" == "linux" ]]; then
            if command -v apt-get &> /dev/null; then
                (type -p wget >/dev/null || sudo apt-get install -y wget) \
                    && sudo mkdir -p -m 755 /etc/apt/keyrings \
                    && out=$(mktemp) && wget -nv -O"$out" https://cli.github.com/packages/githubcli-archive-keyring.gpg \
                    && cat "$out" | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
                    && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
                    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
                    && sudo apt-get update && sudo apt-get install -y gh
            elif command -v dnf &> /dev/null; then
                sudo dnf install -y 'dnf-command(config-manager)' \
                    && sudo dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo \
                    && sudo dnf install -y gh
            else
                echo -e "  ${YELLOW}⚠${NC} Cannot auto-install GitHub CLI — install from https://cli.github.com"
            fi
        fi
        if command -v gh &> /dev/null; then
            echo -e "  ${GREEN}✓${NC} GitHub CLI installed"
        else
            echo -e "  ${YELLOW}!${NC} GitHub CLI not installed — install later from https://cli.github.com"
        fi
    fi
}

# On upgrade, decide what to do with the user's existing soul.md (issue #40).
# Args: <old_soul> <new_default_soul>. The new checkout's default is already at
# <new_default_soul>; <old_soul> is the pre-upgrade file we backed up.
#   return 0 → refreshed: keep the new default in place, save the old one to
#              soul.md.bak-<date>, and print one line saying so.
#   return 1 → preserve : caller restores <old_soul> byte-for-byte (today's behavior).
# It only returns 0 when the old soul is an UNMODIFIED historical default — its
# normalized hash (rapp_brainstem/tests/soul_hash.py) is listed in the manifest —
# AND the new default differs. Any customization, or any uncertainty (no python, no
# manifest, unreadable/undecodable file), fails safe to preserve. It never clobbers.
maybe_refresh_soul() {
    local old="$1" newdef="$2"
    local src_dir="$BRAINSTEM_HOME/src/rapp_brainstem"
    local hasher="$src_dir/tests/soul_hash.py"
    local manifest="$src_dir/tests/soul_defaults.sha256"

    [ -n "${PYTHON_CMD:-}" ] && [ -f "$hasher" ] && [ -f "$manifest" ] || return 1

    local oldhash newhash
    oldhash=$("$PYTHON_CMD" "$hasher" "$old" 2>/dev/null) || return 1
    [ -n "$oldhash" ] || return 1
    # Not an unmodified default (customized or unrecognizable) → preserve.
    awk -v h="$oldhash" '/^[[:space:]]*#/{next} $1==h{f=1; exit} END{exit !f}' "$manifest" || return 1
    # A known default — only refresh if the new default actually differs.
    newhash=$("$PYTHON_CMD" "$hasher" "$newdef" 2>/dev/null) || return 1
    [ -n "$newhash" ] && [ "$oldhash" != "$newhash" ] || return 1

    local bak="$src_dir/soul.md.bak-$(date +%Y%m%d)"
    # Don't clobber an earlier same-day backup (a second refresh on the same date).
    if [ -e "$bak" ]; then
        local n=1
        while [ -e "${bak}-${n}" ]; do n=$((n+1)); done
        bak="${bak}-${n}"
    fi
    cp "$old" "$bak" 2>/dev/null || return 1
    echo -e "  ${GREEN}✓${NC} Refreshed default soul (yours was an unmodified default); backup at ${bak}"
    return 0
}

# ── version pin helpers ──────────────────────────────────────────────────────────
# A pin names a release in one of the tag forms we ship: a bare 0.6.9, the documented
# v0.6.9, or the release tag itself, brainstem-v0.6.9. Nothing else is a version: not a
# branch, HEAD, a commit or a path.
pin_trim() {  # drop leading and trailing whitespace (install.ps1 trims the same characters)
    local v="$1"
    v="${v#"${v%%[![:space:]]*}"}"
    printf '%s' "${v%"${v##*[![:space:]]}"}"
}

pin_is_release_form() {
    [[ "$1" =~ ^(brainstem-v|v)?[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

pin_bare_version() {
    local v="${1#brainstem-}"
    echo "${v#v}"
}

# Resolve PIN_VERSION against the release tags on the remote, before anything on this
# machine changes, and set PIN_TAG and PIN_COMMIT (the commit that tag names). Only
# refs/tags/ count. Prints why and returns 1 when the pin names no release.
resolve_pin() {
    local refs bare cand sha
    if ! pin_is_release_form "$PIN_VERSION"; then
        echo -e "  ${RED}✗${NC} '${PIN_VERSION}' is not a release version. Use X.Y.Z, vX.Y.Z or brainstem-vX.Y.Z, e.g. --version 0.6.9"
        return 1
    fi
    if ! refs=$(GIT_TERMINAL_PROMPT=0 git ls-remote --tags "$REPO_URL" 2>/dev/null); then
        echo -e "  ${RED}✗${NC} Could not read the release tags from ${REPO_URL} to check ${PIN_VERSION}"
        return 1
    fi
    bare=$(pin_bare_version "$PIN_VERSION")
    for cand in "$PIN_VERSION" "brainstem-v${bare}" "v${bare}"; do
        # An annotated tag's peeled line (^{}) names its commit; a lightweight tag's own line does.
        sha=$(printf '%s\n' "$refs" | awk -v r="refs/tags/${cand}^{}" '$2 == r { print $1; exit }')
        [ -n "$sha" ] || sha=$(printf '%s\n' "$refs" | awk -v r="refs/tags/${cand}" '$2 == r { print $1; exit }')
        if [ -n "$sha" ]; then
            PIN_TAG="$cand"
            PIN_COMMIT="$sha"
            return 0
        fi
    done
    echo -e "  ${RED}✗${NC} Version ${PIN_VERSION} not found. Available versions:"
    printf '%s\n' "$refs" \
        | awk '{ t = $2; if (sub(/^refs\/tags\//, "", t) && t !~ /\^/ && t ~ /^(brainstem-)?v[0-9]/) print t }' \
        | sort -V | sed 's/^/    /'
    return 1
}

# Make sure the clone (run inside it) has the resolved release commit, fetching the
# release tag from REPO_URL when it does not. Prints why and returns 1 if it cannot.
pin_fetch_commit() {
    if [ "$(git rev-parse --verify --quiet "${PIN_COMMIT}^{commit}" 2>/dev/null)" != "$PIN_COMMIT" ]; then
        GIT_TERMINAL_PROMPT=0 git fetch --quiet "$REPO_URL" "+refs/tags/${PIN_TAG}:refs/tags/${PIN_TAG}" 2>/dev/null || true
    fi
    if [ "$(git rev-parse --verify --quiet "${PIN_COMMIT}^{commit}" 2>/dev/null)" != "$PIN_COMMIT" ]; then
        echo -e "  ${RED}✗${NC} Could not fetch ${PIN_TAG} (${PIN_COMMIT}) from ${REPO_URL}"
        return 1
    fi
}

# True when the checkout already is the pinned commit, detached (so no later pull can
# move it), with no local edits to the kernel. Run inside the repo.
at_pinned_commit() {
    local head
    head=$(git rev-parse --verify --quiet HEAD 2>/dev/null) || return 1
    [ "$head" = "$PIN_COMMIT" ] || return 1
    if git symbolic-ref --quiet HEAD >/dev/null 2>&1; then return 1; fi
    # shellcheck disable=SC2086 # KERNEL_FILES is a space-separated path list
    [ -z "$(git status --porcelain -- $KERNEL_FILES 2>/dev/null)" ]
}

# A pinned switch must not lose a user's file. `git checkout` refuses to overwrite an
# untracked file at a path the release tracks, silently overwrites an ignored one, and
# the agent restore skips names the release ships. So before the switch, every file on
# disk at a path the release adds (relative to HEAD) moves into the backup; after the
# switch it is kept beside the release's copy as <path>.bak-<date> (the soul refresh's
# naming), and if the switch does not happen it goes back where it was. Run inside the
# repo; <list> holds the paths NUL-separated, <dir> the files set aside.
pin_blockers() {  # <list>
    git diff -z --no-renames --name-only --diff-filter=A HEAD "$PIN_COMMIT" > "$1" 2>/dev/null
}

pin_set_aside() {  # <list> <dir>
    local p
    while IFS= read -r -d '' p; do
        [ -e "$p" ] || [ -L "$p" ] || continue
        mkdir -p "$2/$(dirname "$p")" && mv "$p" "$2/$p" || return 1
    done < "$1"
}

pin_put_back() {  # <list> <dir>
    local p rc=0
    while IFS= read -r -d '' p; do
        [ -e "$2/$p" ] || [ -L "$2/$p" ] || continue
        mkdir -p "$(dirname "$p")" && mv "$2/$p" "$p" || rc=1
    done < "$1"
    return $rc
}

pin_keep_beside() {  # <list> <dir>
    local p bak n rc=0
    while IFS= read -r -d '' p; do
        [ -e "$2/$p" ] || [ -L "$2/$p" ] || continue
        # Identical to the release's copy: nothing of the user's is lost.
        if [ -f "$2/$p" ] && [ -f "$p" ] && cmp -s "$2/$p" "$p"; then continue; fi
        bak="$p.bak-$(date +%Y%m%d)"
        if [ -e "$bak" ] || [ -L "$bak" ]; then
            n=1
            while [ -e "$bak-$n" ] || [ -L "$bak-$n" ]; do n=$((n+1)); done
            bak="$bak-$n"
        fi
        if mv "$2/$p" "$bak"; then
            echo -e "  ${YELLOW}⚠${NC} ${PIN_TAG} ships its own ${p}; yours is kept beside it as ${BRAINSTEM_HOME}/src/${bak}"
        else
            rc=1
        fi
    done < "$1"
    return $rc
}

# A pinned install must run the release's kernel bytes exactly. A checkout does not
# guarantee that: files the switch did not change keep whatever bytes an earlier clone
# wrote, and core.autocrlf=true (the Git for Windows default) writes CRLF line endings.
# Rewrite any kernel file whose raw bytes differ from the release's blob straight from
# the release commit with line-ending conversion off, then report the result.
sync_pinned_kernel() {
    local f want have drift=""
    cd "$BRAINSTEM_HOME/src"
    for f in $KERNEL_FILES; do
        want=$(git rev-parse --verify --quiet "${PIN_COMMIT}:${f}" 2>/dev/null) || continue
        have=$(git hash-object --no-filters -- "$f" 2>/dev/null) || have=""
        if [ "$have" != "$want" ]; then
            rm -f "$f"
            git -c core.autocrlf=false -c core.eol=lf checkout --quiet "$PIN_COMMIT" -- "$f" 2>/dev/null || true
            have=$(git hash-object --no-filters -- "$f" 2>/dev/null) || have=""
        fi
        [ "$have" = "$want" ] || drift="$drift $f"
    done
    if [ -n "$drift" ]; then
        echo -e "  ${YELLOW}⚠${NC} Kernel files still differ from ${PIN_TAG}:${drift}"
    else
        echo -e "  ${GREEN}✓${NC} Kernel matches ${PIN_TAG} byte-for-byte"
    fi
}

# Carry the user state (USER_STATE_FILES, USER_STATE_DIRS, custom agents) of a broken
# install over a re-clone: save_user_state <rapp_brainstem dir> <backup dir> before the
# wipe, restore_user_state <backup dir> <rapp_brainstem dir> after the clone.
save_user_state() {
    local f
    mkdir -p "$2/agents"
    for f in $USER_STATE_FILES; do
        if [ -f "$1/$f" ]; then cp -p "$1/$f" "$2/$f" 2>/dev/null || true; fi
    done
    for f in $USER_STATE_DIRS; do
        if [ -d "$1/$f" ]; then cp -Rp "$1/$f" "$2/$f" 2>/dev/null || true; fi
    done
    if [ -d "$1/agents" ]; then cp -p "$1/agents"/*.py "$2/agents/" 2>/dev/null || true; fi
}

restore_user_state() {
    local f af fn
    for f in $USER_STATE_FILES; do
        if [ -f "$1/$f" ]; then cp -p "$1/$f" "$2/$f" 2>/dev/null || true; fi
    done
    for f in $USER_STATE_DIRS; do
        if [ -d "$1/$f" ] && [ ! -e "$2/$f" ]; then cp -Rp "$1/$f" "$2/$f" 2>/dev/null || true; fi
    done
    mkdir -p "$2/agents"
    for af in "$1/agents"/*.py; do
        [ -f "$af" ] || continue
        fn=$(basename "$af")
        case "$fn" in basic_agent.py|__init__.py) continue ;; esac
        cp -p "$af" "$2/agents/$fn" 2>/dev/null || true
    done
}

install_brainstem() {
    echo ""
    echo "Installing RAPP Brainstem..."
    mkdir -p "$BRAINSTEM_HOME"

    local AGENTS_DIR="$BRAINSTEM_HOME/src/rapp_brainstem/agents"
    local SOUL_FILE="$BRAINSTEM_HOME/src/rapp_brainstem/soul.md"
    local ENV_FILE="$BRAINSTEM_HOME/src/rapp_brainstem/.env"
    local LOCAL_VERSION_FILE="$BRAINSTEM_HOME/src/rapp_brainstem/VERSION"

    if [ -d "$BRAINSTEM_HOME/src/.git" ]; then
        # ── SMART UPDATE: preserve local files, upgrade framework ──
        local LOCAL_VER="0.0.0"
        [ -f "$LOCAL_VERSION_FILE" ] && LOCAL_VER=$(cat "$LOCAL_VERSION_FILE" 2>/dev/null || echo "0.0.0")

        local TARGET_VER NEED_SWITCH=true
        if [ -n "$PIN_VERSION" ]; then
            TARGET_VER="$(pin_bare_version "$PIN_TAG")"
            # main() resolved the pin against the remote. Bring its commit into this clone
            # before touching anything: if that fails, the install stays exactly as it was.
            cd "$BRAINSTEM_HOME/src"
            pin_fetch_commit || exit 1
            # Compare commits, not VERSION strings: a checkout whose VERSION matches can
            # still be a different commit (or a branch a later pull would move).
            if at_pinned_commit; then NEED_SWITCH=false; fi
        else
            TARGET_VER=$(curl -sf "$REMOTE_VERSION_URL" 2>/dev/null || echo "0.0.0")
            if [ "$LOCAL_VER" = "$TARGET_VER" ]; then NEED_SWITCH=false; fi
        fi

        echo "  Local:  v${LOCAL_VER}"
        echo "  Target: v${TARGET_VER}${PIN_VERSION:+ (pinned: ${PIN_TAG})}"

        if [ "$NEED_SWITCH" = false ]; then
            echo -e "  ${GREEN}✓${NC} Already on v${LOCAL_VER}${PIN_VERSION:+ (${PIN_TAG})}"
        else
            echo "  Switching v${LOCAL_VER} → v${TARGET_VER}..."

            # 1. Backup user's local files (soul, custom agents, .env)
            local BACKUP
            BACKUP=$(mktemp -d "${TMPDIR:-/tmp}/brainstem-upgrade-XXXXXX")
            [ -f "$SOUL_FILE" ] && cp "$SOUL_FILE" "$BACKUP/soul.md"
            [ -f "$ENV_FILE" ] && cp "$ENV_FILE" "$BACKUP/.env"
            if [ -d "$AGENTS_DIR" ]; then
                mkdir -p "$BACKUP/agents"
                # Backup ALL agents — user-created ones will be restored
                cp "$AGENTS_DIR"/*.py "$BACKUP/agents/" 2>/dev/null || true
            fi
            echo -e "  ${GREEN}✓${NC} Backed up soul, agents, config"

            # 2. Fetch and checkout target version.
            cd "$BRAINSTEM_HOME/src"
            local PIN_FAILED="" KEEP_BACKUP="" STASH_BEFORE=""
            local BLOCKERS="$BACKUP/pin-blockers" KEPT="$BACKUP/kept"
            if [ -n "$PIN_VERSION" ]; then
                STASH_BEFORE=$(git rev-parse --verify --quiet refs/stash 2>/dev/null || true)
            fi
            git stash --quiet 2>/dev/null || true
            if [ -n "$PIN_VERSION" ]; then
                # Switch to the release commit without forcing: set aside the files the switch
                # would overwrite (pin_blockers), and let git refuse anything else.
                if ! pin_blockers "$BLOCKERS" || ! pin_set_aside "$BLOCKERS" "$KEPT"; then
                    echo -e "  ${RED}✗${NC} Could not set aside the files ${PIN_TAG} would overwrite — keeping existing files (v${LOCAL_VER})"
                    PIN_FAILED=1
                elif git checkout --quiet --detach "$PIN_COMMIT" 2>"$BACKUP/checkout.err"; then
                    echo -e "  ${GREEN}✓${NC} Checked out ${PIN_TAG}"
                else
                    echo -e "  ${RED}✗${NC} Could not check out ${PIN_TAG} — keeping existing files (v${LOCAL_VER}):"
                    sed 's/^/      /' "$BACKUP/checkout.err"
                    PIN_FAILED=1
                fi
                if [ -n "$PIN_FAILED" ]; then
                    # Put the install back as it was: the set-aside files, and the edits the
                    # stash just took.
                    pin_put_back "$BLOCKERS" "$KEPT" || KEEP_BACKUP=1
                    if [ "$(git rev-parse --verify --quiet refs/stash 2>/dev/null || true)" != "$STASH_BEFORE" ]; then
                        git stash pop --quiet 2>/dev/null \
                            || echo -e "  ${YELLOW}⚠${NC} Your uncommitted edits are saved in: git -C \"$BRAINSTEM_HOME/src\" stash list"
                    fi
                fi
            else
                # Guard the fetch: offline (or a black-holed github) must not abort the
                # whole script under `set -e` — we fall back to whatever is already local.
                git fetch origin --tags --quiet 2>/dev/null || true
                git pull --quiet 2>/dev/null || git reset --hard origin/main --quiet 2>/dev/null || echo -e "  ${YELLOW}Warning: Could not update${NC}"
                echo -e "  ${GREEN}✓${NC} Framework updated"
            fi

            # 3. Restore user's local files (merge, don't overwrite)
            # soul.md: refresh it only when the pre-upgrade file was an unmodified
            # historical default (issue #40); any customization is preserved as-is. A pin
            # that did not land restores it byte-for-byte.
            if [ -f "$BACKUP/soul.md" ]; then
                if [ -n "$PIN_FAILED" ] || ! maybe_refresh_soul "$BACKUP/soul.md" "$SOUL_FILE"; then
                    cp "$BACKUP/soul.md" "$SOUL_FILE"
                fi
            fi
            [ -f "$BACKUP/.env" ] && cp "$BACKUP/.env" "$ENV_FILE"
            if [ -d "$BACKUP/agents" ]; then
                # Only restore genuinely user-added agents. Compute the set the repo
                # now ships from the fresh checkout and skip-restore anything in it —
                # otherwise bundled agents (context_memory, manage_memory, hacker_news)
                # get reverted to the backed-up copies on every upgrade (issue #2), so
                # bundled-agent fixes never reach existing users.
                local SHIPPED=""
                for shipped_file in "$AGENTS_DIR"/*.py; do
                    [ -f "$shipped_file" ] || continue
                    SHIPPED="$SHIPPED $(basename "$shipped_file")"
                done
                for agent_file in "$BACKUP/agents"/*.py; do
                    [ -f "$agent_file" ] || continue
                    local fname=$(basename "$agent_file")
                    # Skip core agents that the repo manages
                    case "$fname" in
                        basic_agent.py|__init__.py) continue ;;
                    esac
                    # Skip anything shipped in the fresh checkout (bundled agents)
                    case " $SHIPPED " in *" $fname "*) continue ;; esac
                    # Genuinely user-added agent — keep it
                    cp "$agent_file" "$AGENTS_DIR/$fname"
                done
                echo -e "  ${GREEN}✓${NC} Restored custom agents + soul + config"
            fi
            # A pinned switch that landed keeps each file it set aside beside the release's copy.
            if [ -n "$PIN_VERSION" ] && [ -z "$PIN_FAILED" ]; then
                pin_keep_beside "$BLOCKERS" "$KEPT" || KEEP_BACKUP=1
            fi

            # 4. Clean up backup
            if [ -n "$KEEP_BACKUP" ]; then
                echo -e "  ${YELLOW}⚠${NC} Some of your files could not be put back; they are in ${KEPT}"
            else
                rm -rf "$BACKUP"
            fi
            # A pin that did not land must not go on to launch whatever was there before.
            if [ -n "$PIN_FAILED" ]; then exit 1; fi
            if [ -n "$PIN_VERSION" ]; then
                echo -e "  ${GREEN}✓${NC} Pinned to ${PIN_TAG} (v${TARGET_VER})"
            else
                echo -e "  ${GREEN}✓${NC} Upgrade complete: v${TARGET_VER}"
            fi
        fi
    else
        echo "  Fresh install — cloning repository..."
        # A broken prior install (src present but .git gone) may still hold the user's
        # soul, .env, tokens, memories and custom agents — none of which are in git.
        # Preserve them (USER_STATE_FILES, USER_STATE_DIRS) before wiping so a re-run
        # can't silently destroy the user's work. The common case (no existing src)
        # leaves FRESH_BACKUP empty and skips all of this.
        local FRESH_BACKUP=""
        if [ -d "$BRAINSTEM_HOME/src/rapp_brainstem" ]; then
            FRESH_BACKUP=$(mktemp -d "${TMPDIR:-/tmp}/brainstem-fresh-XXXXXX")
            save_user_state "$BRAINSTEM_HOME/src/rapp_brainstem" "$FRESH_BACKUP"
        fi
        rm -rf "$BRAINSTEM_HOME/src" 2>/dev/null || true
        git clone --quiet "$REPO_URL" "$BRAINSTEM_HOME/src"
        # If pinning, check out the release commit main() resolved, detached.
        local PIN_FAILED=""
        if [ -n "$PIN_VERSION" ]; then
            cd "$BRAINSTEM_HOME/src"
            if ! pin_fetch_commit; then
                PIN_FAILED=1
            elif git checkout --quiet --detach "$PIN_COMMIT" 2>/dev/null; then
                echo -e "  ${GREEN}✓${NC} Checked out ${PIN_TAG}"
            else
                echo -e "  ${RED}✗${NC} Could not check out ${PIN_TAG}"
                PIN_FAILED=1
            fi
        fi
        # Restore any preserved user files over the fresh checkout — also when the pin
        # did not land, so they are never stranded in the temporary backup.
        if [ -n "$FRESH_BACKUP" ]; then
            restore_user_state "$FRESH_BACKUP" "$BRAINSTEM_HOME/src/rapp_brainstem"
            rm -rf "$FRESH_BACKUP"
            echo -e "  ${GREEN}✓${NC} Preserved your soul, agents, memories, tokens, and config"
        fi
        if [ -n "$PIN_FAILED" ]; then exit 1; fi
    fi
    if [ -n "$PIN_VERSION" ]; then
        sync_pinned_kernel
    fi
    echo -e "  ${GREEN}✓${NC} Source code ready"
}

setup_venv() {
    local venv_python="$VENV_DIR/bin/python"

    # Check if venv exists and is healthy
    if [ -x "$venv_python" ]; then
        if "$venv_python" -c "import sys; sys.exit(0)" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} Virtual environment OK"
            return 0
        fi
        echo -e "  ${YELLOW}⚠${NC} Virtual environment broken — recreating..."
        rm -rf "$VENV_DIR"
    fi

    echo "  Creating virtual environment..."
    "$PYTHON_CMD" -m venv "$VENV_DIR" 2>/dev/null || {
        # Some systems need ensurepip first
        "$PYTHON_CMD" -m ensurepip 2>/dev/null || true
        "$PYTHON_CMD" -m venv "$VENV_DIR" || {
            echo -e "  ${RED}✗${NC} Failed to create virtual environment"
            echo "    Try: $PYTHON_CMD -m pip install virtualenv"
            exit 1
        }
    }
    # Ensure pip is up to date inside the venv
    "$VENV_DIR/bin/python" -m pip install --upgrade pip --quiet 2>/dev/null || true
    echo -e "  ${GREEN}✓${NC} Virtual environment ready"
}

setup_deps() {
    echo ""
    echo "Installing dependencies..."
    local req_file="$BRAINSTEM_HOME/src/rapp_brainstem/requirements.txt"
    "$VENV_DIR/bin/pip" install -r "$req_file" --quiet 2>/dev/null || \
        "$VENV_DIR/bin/pip" install -r "$req_file"

    # Verify the critical imports actually work
    if ! "$VENV_DIR/bin/python" -c "import flask, flask_cors, requests, dotenv" 2>/dev/null; then
        echo -e "  ${RED}✗${NC} Dependencies failed to install"
        echo "    Try: $VENV_DIR/bin/pip install -r $req_file"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Dependencies installed"
}

ensure_deps() {
    # Quick import check — only install if something is missing
    if "$VENV_DIR/bin/python" -c "import flask, flask_cors, requests, dotenv" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} Dependencies verified"
        return 0
    fi

    echo -e "  ${YELLOW}⚠${NC} Missing dependencies — installing..."
    local req_file="$BRAINSTEM_HOME/src/rapp_brainstem/requirements.txt"
    "$VENV_DIR/bin/pip" install -r "$req_file" --quiet 2>/dev/null || \
        "$VENV_DIR/bin/pip" install -r "$req_file"

    if ! "$VENV_DIR/bin/python" -c "import flask, flask_cors, requests, dotenv" 2>/dev/null; then
        echo -e "  ${RED}✗${NC} Dependencies failed — try: $VENV_DIR/bin/pip install -r $req_file"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Dependencies installed"
}

install_cli() {
    echo ""
    echo "Installing CLI..."
    mkdir -p "$BRAINSTEM_BIN"

    cat > "$BRAINSTEM_BIN/brainstem" << 'WRAPPER'
#!/bin/bash
BRAINSTEM_HOME="$HOME/.brainstem"
VENV_PYTHON="$BRAINSTEM_HOME/venv/bin/python"
cd "$BRAINSTEM_HOME/src/rapp_brainstem"

# Use venv Python; fall back to creating venv if missing
if [ ! -x "$VENV_PYTHON" ]; then
    echo "  Setting up environment..."
    PYTHON_CMD=$(command -v python3.11 || command -v python3.12 || command -v python3.13 || command -v python3)
    "$PYTHON_CMD" -m venv "$BRAINSTEM_HOME/venv" 2>/dev/null
    "$BRAINSTEM_HOME/venv/bin/pip" install -r requirements.txt --quiet 2>/dev/null || \
        "$BRAINSTEM_HOME/venv/bin/pip" install -r requirements.txt
    VENV_PYTHON="$BRAINSTEM_HOME/venv/bin/python"
fi

# Verify deps on every launch (fast no-op if already installed)
if ! "$VENV_PYTHON" -c "import flask, flask_cors, requests, dotenv" 2>/dev/null; then
    "$BRAINSTEM_HOME/venv/bin/pip" install -r requirements.txt --quiet 2>/dev/null || true
fi

exec "$VENV_PYTHON" brainstem.py "$@"
WRAPPER

    chmod +x "$BRAINSTEM_BIN/brainstem"

    add_to_path() {
        local file="$1"
        # Create shell config if it doesn't exist (common on fresh macOS)
        touch "$file"
        if ! grep -q '\.local/bin' "$file" 2>/dev/null; then
            echo '' >> "$file"
            echo '# RAPP Brainstem' >> "$file"
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$file"
        fi
    }
    add_to_path "$HOME/.bashrc"
    add_to_path "$HOME/.zshrc"
    add_to_path "$HOME/.bash_profile"

    echo -e "  ${GREEN}✓${NC} CLI installed to $BRAINSTEM_BIN/brainstem"
}

create_env() {
    local env_file="$BRAINSTEM_HOME/src/rapp_brainstem/.env"
    if [ ! -f "$env_file" ]; then
        cp "$BRAINSTEM_HOME/src/rapp_brainstem/.env.example" "$env_file" 2>/dev/null || true
    fi
}

launch_brainstem() {
    export PATH="$BRAINSTEM_BIN:/opt/homebrew/bin:/usr/local/bin:$PATH"

    # Always pull latest code before launching — unless a version is pinned: a pull
    # would move the install off the pinned release.
    if [ -z "$PIN_VERSION" ] && [ -d "$BRAINSTEM_HOME/src/.git" ]; then
        cd "$BRAINSTEM_HOME/src"
        git pull --quiet 2>/dev/null || true
    fi

    local venv_python="$VENV_DIR/bin/python"

    # Ensure venv exists (handles edge case where only launch is called)
    if [ ! -x "$venv_python" ]; then
        if [[ -z "$PYTHON_CMD" ]]; then
            PYTHON_CMD=$(find_python) || true
        fi
        if [[ "$(detect_os)" == "macos" ]]; then
            ensure_brew_on_path
        fi
        setup_venv
        ensure_deps
    fi

    local token_file="$BRAINSTEM_HOME/src/rapp_brainstem/.copilot_token"
    local client_id="Iv1.b507a08c87ecfe98"

    # Step 1: Copilot authentication (device code flow)
    local needs_auth=true
    if [ -f "$token_file" ]; then
        # Validate existing token against Copilot API
        local saved_token
        saved_token=$("$venv_python" -c "
import json, sys
try:
    with open('$token_file') as f:
        raw = f.read().strip()
    if raw.startswith('{'):
        print(json.loads(raw).get('access_token',''))
    else:
        print(raw)
except: pass
" 2>/dev/null)
        if [[ -n "$saved_token" ]]; then
            local auth_prefix="token"
            if [[ "$saved_token" != ghu_* ]]; then auth_prefix="Bearer"; fi
            local check_status
            check_status=$(curl -s --max-time 15 -o /dev/null -w "%{http_code}" \
                -H "Authorization: $auth_prefix $saved_token" \
                -H "Accept: application/json" \
                -H "Editor-Version: vscode/1.95.0" \
                -H "Editor-Plugin-Version: copilot/1.0.0" \
                "https://api.github.com/copilot_internal/v2/token" 2>/dev/null) || true
            if [[ "$check_status" == "200" ]]; then
                echo -e "  ${GREEN}✓${NC} Already authenticated with GitHub Copilot"
                needs_auth=false
            elif [[ -z "$check_status" || "$check_status" == "000" ]]; then
                # curl never reached GitHub (offline, captive portal, timeout) — that
                # says nothing about the token. Keep it; the server retries live.
                echo -e "  ${YELLOW}⚠${NC} Couldn't verify the saved token (no network) — keeping it"
                needs_auth=false
            else
                echo -e "  ${YELLOW}⚠${NC} Saved token expired — re-authenticating..."
                rm -f "$token_file"
            fi
        else
            rm -f "$token_file"
        fi
    fi

    if [[ "$needs_auth" == true ]]; then
        echo ""
        echo -e "  ${CYAN}Authenticating with GitHub Copilot...${NC}"
        echo ""

        # Best-effort auth: disable `set -e` for the whole block. Every curl and JSON
        # parse below tolerates failure (empty response when offline), and the code
        # already handles those cases gracefully — but under `set -e` the very first
        # failed command substitution would abort the installer before the server can
        # start. The user can always finish signing in later at /login.
        set +e

        # Request device code
        local device_resp
        device_resp=$(curl -fsSL --max-time 15 -X POST "https://github.com/login/device/code" \
            -H "Accept: application/json" \
            -H "Content-Type: application/x-www-form-urlencoded" \
            -d "client_id=${client_id}" 2>/dev/null)

        local user_code device_code interval verify_uri
        user_code=$(echo "$device_resp" | "$venv_python" -c "import sys,json; print(json.load(sys.stdin)['user_code'])" 2>/dev/null)
        device_code=$(echo "$device_resp" | "$venv_python" -c "import sys,json; print(json.load(sys.stdin)['device_code'])" 2>/dev/null)
        interval=$(echo "$device_resp" | "$venv_python" -c "import sys,json; print(json.load(sys.stdin).get('interval',5))" 2>/dev/null)
        verify_uri=$(echo "$device_resp" | "$venv_python" -c "import sys,json; print(json.load(sys.stdin)['verification_uri'])" 2>/dev/null)

        if [[ -z "$user_code" || -z "$device_code" ]]; then
            echo -e "  ${YELLOW}!${NC} Could not start auth — you can sign in at http://localhost:7071/login"
        else
            echo "  ┌─────────────────────────────────────────┐"
            echo -e "  │  Your code: ${CYAN}${user_code}${NC}                  │"
            echo "  └─────────────────────────────────────────┘"
            echo ""
            echo "  Opening browser to authorize..."

            # Open browser
            open "$verify_uri" 2>/dev/null || xdg-open "$verify_uri" 2>/dev/null || true

            echo "  Waiting for authorization..."
            echo ""

            local token_json=""
            for i in $(seq 1 60); do
                sleep "${interval:-5}"
                local poll_resp
                poll_resp=$(curl -fsSL --max-time 15 -X POST "https://github.com/login/oauth/access_token" \
                    -H "Accept: application/json" \
                    -H "Content-Type: application/x-www-form-urlencoded" \
                    -d "client_id=${client_id}&device_code=${device_code}&grant_type=urn:ietf:params:oauth:grant-type:device_code" 2>/dev/null) || true

                local access_token error
                access_token=$(echo "$poll_resp" | "$venv_python" -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null)
                error=$(echo "$poll_resp" | "$venv_python" -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',''))" 2>/dev/null)

                if [[ -n "$access_token" ]]; then
                    # Save token file (same format brainstem.py expects)
                    "$venv_python" -c "
import sys, json
d = json.loads(sys.argv[1])
out = {'access_token': d['access_token']}
if d.get('refresh_token'): out['refresh_token'] = d['refresh_token']
with open(sys.argv[2], 'w') as f: json.dump(out, f)
" "$poll_resp" "$token_file"

                    # Validate Copilot access immediately
                    local copilot_check copilot_status
                    copilot_check=$(curl -s --max-time 15 -w "\n%{http_code}" \
                        -H "Authorization: token $access_token" \
                        -H "Accept: application/json" \
                        -H "Editor-Version: vscode/1.95.0" \
                        -H "Editor-Plugin-Version: copilot/1.0.0" \
                        "https://api.github.com/copilot_internal/v2/token" 2>/dev/null) || true
                    copilot_status=$(echo "$copilot_check" | tail -1)

                    if [[ "$copilot_status" == "200" ]]; then
                        echo -e "  ${GREEN}✓${NC} Authenticated — Copilot access confirmed"
                    elif [[ "$copilot_status" == "403" ]]; then
                        echo ""
                        echo -e "  ${RED}✗${NC} This GitHub account does NOT have Copilot access."
                        echo ""
                        echo -e "  Either:"
                        echo -e "    1. Sign up for Copilot: ${CYAN}https://github.com/github-copilot/signup${NC}"
                        echo -e "    2. Re-run this installer and sign in with a different GitHub account"
                        echo ""
                        rm -f "$token_file"
                    else
                        echo -e "  ${GREEN}✓${NC} Authenticated with GitHub"
                    fi
                    break
                fi

                if [[ "$error" == "expired_token" ]]; then
                    echo -e "  ${YELLOW}!${NC} Auth timed out — sign in at http://localhost:7071/login"
                    break
                fi

                if [[ "$error" != "authorization_pending" && "$error" != "slow_down" && -n "$error" ]]; then
                    echo -e "  ${YELLOW}!${NC} Auth error: $error — sign in at http://localhost:7071/login"
                    break
                fi
            done
        fi
        set -e   # end best-effort auth block
    fi

    # Step 2: Launch brainstem
    echo ""
    echo -e "  ${CYAN}Starting RAPP Brainstem...${NC}"
    echo ""

    cd "$BRAINSTEM_HOME/src/rapp_brainstem"

    # Kill any existing brainstem on port 7071 before starting
    local existing_pid
    existing_pid=$(lsof -ti:7071 2>/dev/null | head -1)
    if [ -n "$existing_pid" ]; then
        echo -e "  ${YELLOW}⚠${NC} Stopping existing server (PID $existing_pid)..."
        kill "$existing_pid" 2>/dev/null
        sleep 1
    fi

    # Open the browser once the server actually answers (#14) — a fixed delay
    # races cold startups (token exchange, dep installs) and lands the user on
    # a dead-port error page. Poll /health, then open; after 60s open anyway so
    # the user still gets the tab (with the URL bar filled in) on a slow start.
    (
        for _ in $(seq 1 60); do
            if curl -sf -o /dev/null --max-time 1 "http://localhost:7071/health" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        open "http://localhost:7071" 2>/dev/null || xdg-open "http://localhost:7071" 2>/dev/null || true
    ) &

    # Final dep safety net — if somehow we got here without deps, fix it
    if ! "$venv_python" -c "import flask, flask_cors, requests, dotenv" 2>/dev/null; then
        echo -e "  ${YELLOW}⚠${NC} Fixing missing dependencies..."
        "$VENV_DIR/bin/pip" install -r "$BRAINSTEM_HOME/src/rapp_brainstem/requirements.txt" --quiet 2>/dev/null || \
            "$VENV_DIR/bin/pip" install -r "$BRAINSTEM_HOME/src/rapp_brainstem/requirements.txt"
    fi

    # Use exec to replace shell — but only if stdin is a terminal.
    # When piped (curl | bash), exec can lose the TTY and hang.
    if [ -t 0 ]; then
        exec "$venv_python" brainstem.py
    elif ( : </dev/tty ) 2>/dev/null; then
        # Piped installer with a USABLE controlling terminal — reattach stdin.
        # Test by opening it: the /dev/tty node exists even without a controlling
        # terminal (ssh without -t, CI), where only the open fails — a bare `-e`
        # check would take this branch and die on the redirect.
        "$venv_python" brainstem.py </dev/tty
    else
        # No controlling terminal at all (ssh without -t, CI, a container). Reattaching
        # /dev/tty would error out; just run the server on the inherited stdin.
        "$venv_python" brainstem.py
    fi
}

main() {
    # The pin comes from BRAINSTEM_VERSION or --version (which wins). Surrounding
    # whitespace is dropped first; an empty --version is then refused (below) rather than
    # silently installing main.
    PIN_VERSION=$(pin_trim "${BRAINSTEM_VERSION:-}")
    if [ -n "$PIN_VERSION" ]; then PIN_SOURCE="BRAINSTEM_VERSION"; fi
    while [ $# -gt 0 ]; do
        case "$1" in
            --version)
                local value=""
                if [ $# -ge 2 ]; then value=$(pin_trim "$2"); shift 2; else shift; fi
                if [ -n "$value" ]; then
                    PIN_VERSION="$value"
                    PIN_SOURCE="--version"
                else
                    PIN_ERROR="--version needs a value, e.g. --version 0.6.9"
                fi
                ;;
            *)
                shift
                ;;
        esac
    done

    print_banner

    # A malformed pin stops here, before anything on the machine changes.
    if [ -n "$PIN_ERROR" ]; then
        echo -e "  ${RED}✗${NC} ${PIN_ERROR}"
        exit 1
    fi

    if [ -n "$PIN_VERSION" ]; then
        echo -e "  ${CYAN}Pinning to version: ${PIN_VERSION} (from ${PIN_SOURCE})${NC}"
        # Check the pin against the release tags on the remote before anything on this
        # machine changes: no prerequisite install, backup, stash, wipe or clone yet. The
        # check needs git, so a machine without git gets it first.
        if ! command -v git &> /dev/null; then
            if [[ "$(detect_os)" == "macos" ]]; then ensure_brew_on_path; fi
            check_git
        fi
        resolve_pin || exit 1
        echo -e "  ${GREEN}✓${NC} ${PIN_VERSION} is release ${PIN_TAG} (${PIN_COMMIT:0:12})"
        echo ""
    fi

    # Check if this is an upgrade of an existing install
    # Skip the shortcut when --version is specified (always go through install_brainstem)
    if [ -z "$PIN_VERSION" ] && [ -d "$BRAINSTEM_HOME/src/.git" ]; then
        echo "Checking for updates..."
        if ! check_for_upgrade; then
            # Already up to date — still verify everything works before launching
            check_prereqs
            setup_venv
            ensure_deps
            install_cli
            create_env
            export PATH="$BRAINSTEM_BIN:/opt/homebrew/bin:/usr/local/bin:$PATH"
            launch_brainstem
            exit $?  # launch uses exec, but guard against fall-through
        fi
        # Upgrade available — fall through to full install path
    fi

    check_prereqs
    install_brainstem
    setup_venv
    setup_deps
    install_cli
    create_env

    # Make sure brainstem and gh are on PATH for this session
    export PATH="$BRAINSTEM_BIN:/opt/homebrew/bin:/usr/local/bin:$PATH"

    local installed_version
    installed_version=$(cat "$BRAINSTEM_HOME/src/rapp_brainstem/VERSION" 2>/dev/null | tr -d '[:space:]')

    echo ""
    echo "═══════════════════════════════════════════════════"
    echo -e "  ${GREEN}✓ RAPP Brainstem v${installed_version} installed!${NC}"
    echo "═══════════════════════════════════════════════════"
    echo ""

    launch_brainstem
}

main "$@"
