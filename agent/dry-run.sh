#!/bin/sh
# Dry-run harness for the Wiretide agent skeleton.
# Starts a local mock backend and runs the agent with DRY_RUN enabled.

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
MOCK_PORT="${MOCK_PORT:-9000}"
SHARED_TOKEN="${SHARED_TOKEN:-drytoken}"
STATE_DIR="${STATE_DIR:-/tmp/wiretide-dry}"
LOG_FILE="${LOG_FILE:-/tmp/wiretide-dry.log}"
INTERVAL="${INTERVAL:-5}"
TIMEOUT_SECS="${TIMEOUT_SECS:-25}"

mock_pid=""
cleanup() {
  [ -n "$mock_pid" ] && kill "$mock_pid" 2>/dev/null || true
}
trap cleanup EXIT

python3 "$SCRIPT_DIR/mock_backend.py" --port "$MOCK_PORT" --shared-token "$SHARED_TOKEN" &
mock_pid=$!
echo "[dry-run] mock backend pid=$mock_pid on port $MOCK_PORT token=$SHARED_TOKEN"
sleep 1

env \
  CONTROLLER_URL="http://127.0.0.1:$MOCK_PORT" \
  SHARED_TOKEN="$SHARED_TOKEN" \
  STATE_DIR="$STATE_DIR" \
  LOG_FILE="$LOG_FILE" \
  INTERVAL="$INTERVAL" \
  DRY_RUN=1 \
  DEVICE_TYPE="access_point" \
  AGENT_VERSION="dry-run" \
  timeout "$TIMEOUT_SECS" sh "$SCRIPT_DIR/agent-skeleton.sh" || true

echo "[dry-run] log output:"
tail -n 50 "$LOG_FILE" || true
