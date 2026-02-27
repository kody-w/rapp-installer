#!/bin/bash
# CommunityRAPP — One-line installer
# Usage: curl -fsSL https://raw.githubusercontent.com/kody-w/rapp-installer/main/community_rapp/install.sh | bash
#
# Requires: GitHub CLI (gh) authenticated with access to kody-w/CommunityRAPP

set -e
RED="\033[0;31m" GREEN="\033[0;32m" YELLOW="\033[1;33m" BLUE="\033[0;34m" NC="\033[0m"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  CommunityRAPP — Local Setup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ── Prerequisites ────────────────────────────────────────────
echo -e "${YELLOW}Checking prerequisites...${NC}"

# GitHub CLI
if ! command -v gh &>/dev/null; then
    echo -e "${YELLOW}Installing GitHub CLI...${NC}"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install gh 2>/dev/null || { echo -e "${RED}Install Homebrew first: https://brew.sh${NC}"; exit 1; }
    else
        (type -p wget >/dev/null || (sudo apt update && sudo apt-get install wget -y)) \
        && sudo mkdir -p -m 755 /etc/apt/keyrings \
        && out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        && cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
        && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
        && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli-stable.list > /dev/null \
        && sudo apt update && sudo apt install gh -y
    fi
fi
echo -e "${GREEN}[OK] GitHub CLI${NC}"

# Check gh auth
if ! gh auth status &>/dev/null 2>&1; then
    echo -e "${YELLOW}Not logged into GitHub CLI. Running: gh auth login${NC}"
    gh auth login
fi
GH_USER=$(gh api user --jq '.login' 2>/dev/null)
echo -e "${GREEN}[OK] Authenticated as @${GH_USER}${NC}"

# Check repo access
if ! gh api repos/kody-w/CommunityRAPP --jq '.name' &>/dev/null 2>&1; then
    echo -e "${RED}[X] No access to kody-w/CommunityRAPP${NC}"
    echo -e "${RED}    Request contributor access from a repo maintainer.${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] Repo access confirmed${NC}"

# Python 3.11
find_python311() {
    for cmd in python3.11 python311; do
        if command -v $cmd &>/dev/null; then
            ver=$($cmd --version 2>&1)
            [[ $ver == *"3.11"* ]] && echo $cmd && return 0
        fi
    done
    if [[ "$OSTYPE" == "darwin"* ]]; then
        for p in /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11; do
            [[ -x $p ]] && echo $p && return 0
        done
    fi
    return 1
}

PYTHON_CMD=$(find_python311) || {
    echo -e "${YELLOW}Installing Python 3.11...${NC}"
    if [[ "$OSTYPE" == "darwin"* ]]; then brew install python@3.11; else sudo apt-get update && sudo apt-get install -y python3.11 python3.11-venv; fi
    PYTHON_CMD=$(find_python311) || { echo -e "${RED}Failed to install Python 3.11${NC}"; exit 1; }
}
echo -e "${GREEN}[OK] Python 3.11: $PYTHON_CMD${NC}"

# Azure Functions Core Tools
if ! command -v func &>/dev/null; then
    echo -e "${YELLOW}Installing Azure Functions Core Tools...${NC}"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew tap azure/functions && brew install azure-functions-core-tools@4
    else
        npm install -g azure-functions-core-tools@4 2>/dev/null || {
            echo -e "${YELLOW}npm not found, installing via apt...${NC}"
            curl -sL https://deb.nodesource.com/setup_20.x | sudo -E bash -
            sudo apt-get install -y nodejs
            npm install -g azure-functions-core-tools@4
        }
    fi
fi
echo -e "${GREEN}[OK] Azure Functions Core Tools${NC}"

# ── Clone & Setup ────────────────────────────────────────────
echo ""
echo -e "${YELLOW}Cloning CommunityRAPP...${NC}"
if [ -d "CommunityRAPP" ]; then
    cd CommunityRAPP && git pull
else
    gh repo clone kody-w/CommunityRAPP && cd CommunityRAPP
fi
echo -e "${GREEN}[OK] Repository cloned${NC}"

echo -e "${YELLOW}Setting up Python environment...${NC}"
[ -d ".venv" ] && rm -rf .venv
$PYTHON_CMD -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q && pip install -r requirements.txt -q
echo -e "${GREEN}[OK] Dependencies installed${NC}"

# ── Config ───────────────────────────────────────────────────
if [ ! -f "local.settings.json" ]; then
    echo ""
    echo -e "${YELLOW}No local.settings.json found.${NC}"
    echo -e "Two options:"
    echo -e "  1. Deploy to Azure first: click the Deploy button in README.md"
    echo -e "     Then copy the setup script from the Outputs tab."
    echo -e "  2. Copy the template and fill in your Azure values:"
    echo -e "     cp local.settings.template.json local.settings.json"
    echo ""
fi

# ── Done ─────────────────────────────────────────────────────
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  CommunityRAPP is ready!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Next steps:"
echo "  cd CommunityRAPP"
echo "  source .venv/bin/activate"
echo ""
echo "  # If you have local.settings.json configured:"
echo "  func start"
echo ""
echo "  # If not, deploy to Azure first:"
echo "  # Click the Deploy to Azure button in README.md"
echo ""
