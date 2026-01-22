#!/bin/bash
set -e

# RAPP Installer - https://github.com/kody-w/rapp-installer
# This script is PUBLIC. It clones the PRIVATE RAPP repo with auth.

RAPP_HOME="$HOME/.rapp"
RAPP_BIN="$HOME/.local/bin"
RAPP_REPO="https://github.com/kody-w/RAPP.git"  # Private repo

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Function to read input - handles piped execution by reading from /dev/tty
read_input() {
    local prompt="$1"
    local default="$2"
    local result

    # Try to read from /dev/tty (works when script is piped)
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
    echo "  ██████╗  █████╗ ██████╗ ██████╗ "
    echo "  ██╔══██╗██╔══██╗██╔══██╗██╔══██╗"
    echo "  ██████╔╝███████║██████╔╝██████╔╝"
    echo "  ██╔══██╗██╔══██║██╔═══╝ ██╔═══╝ "
    echo "  ██║  ██║██║  ██║██║     ██║     "
    echo "  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝     "
    echo -e "${NC}"
    echo "  Rapid AI Agent Production Pipeline"
    echo ""
}

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."

    # Python 3.11+
    if command -v python3 &> /dev/null; then
        version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        major=$(echo $version | cut -d. -f1)
        minor=$(echo $version | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            echo -e "  ${GREEN}✓${NC} Python $version"
        else
            echo -e "  ${RED}✗${NC} Python 3.11+ required (found $version)"
            echo "    Install from https://python.org"
            exit 1
        fi
    else
        echo -e "  ${RED}✗${NC} Python 3.11+ required"
        echo "    Install from https://python.org"
        exit 1
    fi

    # Git
    if command -v git &> /dev/null; then
        echo -e "  ${GREEN}✓${NC} Git $(git --version | cut -d' ' -f3)"
    else
        echo -e "  ${RED}✗${NC} Git required"
        echo "    Install from https://git-scm.com"
        exit 1
    fi

    # Azure CLI (optional at install, required at runtime)
    if command -v az &> /dev/null; then
        az_version=$(az --version 2>/dev/null | head -1 | awk '{print $2}' | tr -d '()')
        echo -e "  ${GREEN}✓${NC} Azure CLI $az_version"
    else
        echo -e "  ${YELLOW}⚠${NC} Azure CLI not found (required for setup)"
        echo "    Install later: https://aka.ms/installazurecli"
    fi
}

# GitHub Authentication
setup_github_auth() {
    echo ""
    echo -e "${YELLOW}GitHub Authentication Required${NC}"
    echo "─────────────────────────────────"
    echo "RAPP source code is in a private repository."
    echo ""

    # Check if gh CLI is available and authenticated
    if command -v gh &> /dev/null; then
        if gh auth status &> /dev/null 2>&1; then
            echo -e "  ${GREEN}✓${NC} Already authenticated with GitHub CLI"
            return 0
        else
            echo "Authenticating with GitHub CLI..."
            gh auth login
            return 0
        fi
    fi

    # Check for existing git credentials (try a lightweight check)
    if git ls-remote "$RAPP_REPO" &> /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} Git credentials found"
        return 0
    fi

    # Manual auth flow
    echo "Options to authenticate:"
    echo ""
    echo "  1. Install GitHub CLI (recommended):"
    echo "     brew install gh && gh auth login"
    echo ""
    echo "  2. Use HTTPS with personal access token"
    echo "     When prompted, enter your GitHub username and PAT as password"
    echo ""
    echo "  3. Use SSH key (if already configured)"
    echo ""

    has_auth=$(read_input "Do you have GitHub access configured? (y/n): " "n")

    if [[ "$has_auth" != "y" && "$has_auth" != "Y" ]]; then
        echo ""
        echo "To get access:"
        echo "  1. Request access to github.com/kody-w/RAPP"
        echo "  2. Create a Personal Access Token: https://github.com/settings/tokens"
        echo "  3. Run this installer again"
        exit 1
    fi
}

# Clone/update private repo
install_rapp() {
    echo ""
    echo "Installing RAPP..."
    mkdir -p "$RAPP_HOME"

    if [ -d "$RAPP_HOME/src/.git" ]; then
        echo "  Updating existing installation..."
        cd "$RAPP_HOME/src"
        git pull --quiet || {
            echo -e "  ${YELLOW}Warning: Could not update, using existing version${NC}"
        }
    else
        echo "  Cloning repository (this may prompt for credentials)..."
        rm -rf "$RAPP_HOME/src" 2>/dev/null || true

        if ! git clone --quiet "$RAPP_REPO" "$RAPP_HOME/src"; then
            echo -e "  ${RED}✗${NC} Failed to clone repository"
            echo ""
            echo "  Possible causes:"
            echo "    - No access to private repository"
            echo "    - Invalid credentials"
            echo "    - Network issues"
            echo ""
            echo "  Request access at: github.com/kody-w/RAPP"
            exit 1
        fi
    fi
    echo -e "  ${GREEN}✓${NC} Source code ready"
}

# Create venv and install deps
setup_environment() {
    echo ""
    echo "Setting up Python environment..."
    cd "$RAPP_HOME"

    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi

    # Activate venv
    source venv/bin/activate

    # Upgrade pip quietly
    pip install --upgrade pip --quiet 2>/dev/null

    # Install dependencies
    echo "  Installing dependencies (this may take a moment)..."
    if [ -f "src/requirements.txt" ]; then
        pip install -r src/requirements.txt --quiet 2>/dev/null || {
            echo -e "  ${YELLOW}Warning: Some packages may have failed${NC}"
            pip install -r src/requirements.txt
        }
    fi

    echo -e "  ${GREEN}✓${NC} Dependencies installed"
}

# Create CLI wrapper
install_cli() {
    echo ""
    echo "Installing CLI..."
    mkdir -p "$RAPP_BIN"

    # Create the wrapper script
    cat > "$RAPP_BIN/rapp" << 'WRAPPER'
#!/bin/bash
RAPP_HOME="$HOME/.rapp"

# Activate virtual environment
source "$RAPP_HOME/venv/bin/activate"

# Set Python path
export PYTHONPATH="$RAPP_HOME/src:$PYTHONPATH"

# Run CLI
python -m rapp_cli "$@"
WRAPPER

    chmod +x "$RAPP_BIN/rapp"

    # Add to PATH in shell configs
    add_to_path() {
        local file="$1"
        if [ -f "$file" ]; then
            if ! grep -q '\.local/bin' "$file" 2>/dev/null; then
                echo '' >> "$file"
                echo '# RAPP CLI' >> "$file"
                echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$file"
            fi
        fi
    }

    add_to_path "$HOME/.bashrc"
    add_to_path "$HOME/.zshrc"
    add_to_path "$HOME/.bash_profile"

    echo -e "  ${GREEN}✓${NC} CLI installed to $RAPP_BIN/rapp"
}

# Main installation
main() {
    print_banner
    check_prerequisites
    setup_github_auth
    install_rapp
    setup_environment
    install_cli

    echo ""
    echo "═══════════════════════════════════════════════════"
    echo -e "  ${GREEN}✓ RAPP installed successfully!${NC}"
    echo "═══════════════════════════════════════════════════"
    echo ""
    echo "  Get started:"
    echo "    rapp              Start RAPP (opens web UI)"
    echo "    rapp setup        Configure Azure connection"
    echo "    rapp --help       Show all commands"
    echo ""
    echo "  Restart your terminal or run:"
    echo "    source ~/.bashrc   # or ~/.zshrc"
    echo ""
}

# Run main
main
