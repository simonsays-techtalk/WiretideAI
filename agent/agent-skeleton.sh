#!/bin/sh
# Wiretide Agent (skeleton)
# This is a reference shell script illustrating the agent flow on OpenWrt.
# It is NOT production-ready: fill in controller_url/shared_token/device_id handling per your environment.

set -euo pipefail

CONFIG_FILE="/etc/wiretide/agent.conf"
STATE_DIR="/tmp/wiretide"
DEVICE_ID_FILE="$STATE_DIR/device_id"

controller_url="${CONTROLLER_URL:-http://127.0.0.1:9000}"
shared_token="${SHARED_TOKEN:-}"
device_id="${DEVICE_ID:-}"

mkdir -p "$STATE_DIR"

load_config() {
  [ -f "$CONFIG_FILE" ] && . "$CONFIG_FILE"
  [ -f "$DEVICE_ID_FILE" ] && device_id="$(cat "$DEVICE_ID_FILE")"
}

save_device_id() {
  echo "$device_id" > "$DEVICE_ID_FILE"
}

register_once() {
  if [ -n "$device_id" ]; then
    return 0
  fi
  payload="{\"hostname\":\"$(hostname)\",\"ssh_enabled\":true}"
  resp="$(wget -qO- \
    --header="Content-Type: application/json" \
    --header="X-Shared-Token: $shared_token" \
    --post-data="$payload" \
    "$controller_url/register" || true)"
  device_id="$(echo "$resp" | jsonfilter -e '@.device_id' 2>/dev/null || true)"
  if [ -n "$device_id" ]; then
    save_device_id
  fi
}

send_status() {
  [ -z "$device_id" ] && return 0
  payload="{\"device_id\":$device_id,\"dns_ok\":true,\"ntp_ok\":true,\"ssh_enabled\":true}"
  wget -qO- \
    --header="Content-Type: application/json" \
    --header="X-Shared-Token: $shared_token" \
    --post-data="$payload" \
    "$controller_url/status" >/dev/null 2>&1 || true
}

fetch_config() {
  [ -z "$device_id" ] && return 0
  cfg="$(wget -qO- \
    --header="X-Shared-Token: $shared_token" \
    "$controller_url/config?device_id=$device_id" 2>/dev/null || true)"
  echo "$cfg" | grep -q "package" || return 0
  # TODO: validate sha256 and apply according to package type.
}

recover_token() {
  new_token="$(wget -qO- "$controller_url/token/current" 2>/dev/null | jsonfilter -e '@.shared_token' || true)"
  if [ -n "$new_token" ]; then
    shared_token="$new_token"
  fi
}

main_loop() {
  while true; do
    load_config
    register_once
    send_status
    fetch_config
    sleep 30
  done
}

# Entry
if [ -z "$shared_token" ]; then
  echo "Shared token not set; export SHARED_TOKEN or set in $CONFIG_FILE" >&2
  exit 1
fi

main_loop
