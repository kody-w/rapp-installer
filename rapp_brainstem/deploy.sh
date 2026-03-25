#!/usr/bin/env bash
# deploy.sh — One-shot deploy to Copilot Studio
#
# Usage:
#   ./deploy.sh              # push only (default)
#   ./deploy.sh --pull       # pull first, then push
#   ./deploy.sh --changes    # show diff, don't push
#   ./deploy.sh --clone      # fresh clone from server
#
# Reads connection details from .mcs/conn.json automatically.
# Push = Publish (no separate publish step needed).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="$SCRIPT_DIR/copilot-studio/RAPP Brainstem"
MANAGE_AGENT="$HOME/.claude/plugins/cache/skills-for-copilot-studio/copilot-studio/1.0.4/scripts/manage-agent.bundle.js"

# Read conn.json
CONN_JSON="$WORKSPACE/.mcs/conn.json"
if [[ ! -f "$CONN_JSON" ]]; then
    echo "ERROR: No .mcs/conn.json found. Clone an agent first."
    exit 1
fi

TENANT_ID=$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['AccountInfo']['TenantId'])" "$CONN_JSON")
ENV_ID=$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['EnvironmentId'])" "$CONN_JSON")
ENV_URL=$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['DataverseEndpoint'])" "$CONN_JSON")
MGMT_URL=$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['AgentManagementEndpoint'])" "$CONN_JSON")

COMMON_ARGS=(
    --workspace "$WORKSPACE"
    --tenant-id "$TENANT_ID"
    --environment-id "$ENV_ID"
    --environment-url "$ENV_URL"
    --agent-mgmt-url "$MGMT_URL"
)

ACTION="${1:-push}"

case "$ACTION" in
    --pull|pull)
        echo "=== Pulling from Copilot Studio ==="
        node "$MANAGE_AGENT" pull "${COMMON_ARGS[@]}"
        echo ""
        echo "=== Pushing local changes ==="
        node "$MANAGE_AGENT" push "${COMMON_ARGS[@]}"
        ;;
    --changes|changes|--diff|diff)
        echo "=== Local vs Remote Changes ==="
        node "$MANAGE_AGENT" changes "${COMMON_ARGS[@]}"
        ;;
    --clone|clone)
        AGENT_ID=$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['AgentId'])" "$CONN_JSON")
        echo "=== Cloning agent $AGENT_ID ==="
        node "$MANAGE_AGENT" clone "${COMMON_ARGS[@]}" --agent-id "$AGENT_ID"
        ;;
    --push|push|"")
        echo "=== Pushing to Copilot Studio ==="
        echo "    (Push = Publish. No separate publish step needed.)"
        echo ""
        node "$MANAGE_AGENT" push "${COMMON_ARGS[@]}"
        ;;
    *)
        echo "Usage: $0 [push|pull|changes|clone]"
        exit 1
        ;;
esac

echo ""
echo "Done."
