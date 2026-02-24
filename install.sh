#!/bin/bash
set -e

# RAPP Brainstem Installer
# Usage: curl -fsSL https://kody-w.github.io/rapp-installer/install.sh | bash

BRAINSTEM_HOME="$HOME/.brainstem"
BRAINSTEM_BIN="$HOME/.local/bin"
REPO_URL="https://github.com/kody-w/rapp-installer.git"

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

find_python() {
    for cmd in python3.11 python3.12 python3.13 python3; do
        if command -v "$cmd" &> /dev/null; then
            version=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
            major=$(echo "$version" | cut -d. -f1)
            minor=$(echo "$version" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
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

check_prereqs() {
    echo "Checking prerequisites..."

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

install_brainstem() {
    echo ""
    echo "Installing RAPP Brainstem..."
    mkdir -p "$BRAINSTEM_HOME"

    if [ -d "$BRAINSTEM_HOME/src/.git" ]; then
        echo "  Updating existing installation..."
        cd "$BRAINSTEM_HOME/src"
        git pull --quiet 2>/dev/null || echo -e "  ${YELLOW}Warning: Could not update${NC}"
    else
        echo "  Cloning repository..."
        rm -rf "$BRAINSTEM_HOME/src" 2>/dev/null || true
        git clone --quiet "$REPO_URL" "$BRAINSTEM_HOME/src"
    fi
    echo -e "  ${GREEN}✓${NC} Source code ready"
}

setup_deps() {
    echo ""
    echo "Installing dependencies..."
    cd "$BRAINSTEM_HOME/src/rapp_brainstem"
    "$PYTHON_CMD" -m pip install -r requirements.txt --quiet 2>/dev/null || \
        "$PYTHON_CMD" -m pip install -r requirements.txt
    echo -e "  ${GREEN}✓${NC} Dependencies installed"
}

install_cli() {
    echo ""
    echo "Installing CLI..."
    mkdir -p "$BRAINSTEM_BIN"

    cat > "$BRAINSTEM_BIN/brainstem" << WRAPPER
#!/bin/bash
cd "$BRAINSTEM_HOME/src/rapp_brainstem"
exec $PYTHON_CMD brainstem.py "\$@"
WRAPPER

    chmod +x "$BRAINSTEM_BIN/brainstem"

    add_to_path() {
        local file="$1"
        if [ -f "$file" ]; then
            if ! grep -q '\.local/bin' "$file" 2>/dev/null; then
                echo '' >> "$file"
                echo '# RAPP Brainstem' >> "$file"
                echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$file"
            fi
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

main() {
    print_banner
    check_prereqs
    install_brainstem
    setup_deps
    install_cli
    create_env

    echo ""
    echo "═══════════════════════════════════════════════════"
    echo -e "  ${GREEN}✓ RAPP Brainstem installed!${NC}"
    echo "═══════════════════════════════════════════════════"
    echo ""
    echo "  Get started:"
    echo -e "    ${CYAN}gh auth login${NC}        # authenticate with GitHub"
    echo -e "    ${CYAN}brainstem${NC}            # start the server (localhost:7071)"
    echo ""
    echo "  Then open http://localhost:7071 in your browser."
    echo ""
    echo "  Restart your terminal or run:"
    echo "    source ~/.bashrc   # or ~/.zshrc"
    echo ""
}

main
